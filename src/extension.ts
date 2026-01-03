import * as vscode from 'vscode';
import { CodeHistoryDiffPlayer, virtualFileSystemRegister } from './diffView';
import { GenTestCodeLensProvider } from './inlineCodeLens';
import { setWebRoot, TesterWebViewProvider } from './sidebarView';
import { TesterSession } from './client';
import { detectCodeLang, extractGenTestCode, extractRefTestCode, langSuffix, shouldGenTestPrompt } from './textUtils';
import { marked } from 'marked';
import { ExtensionMetadata } from './constants';
import { showANewEditorForInput } from './utils';

let activeSession: TesterSession | undefined;

export function activate(context: vscode.ExtensionContext): void {
    const viewId = 'testView.sidebar';
    const testerWebViewProvider = new TesterWebViewProvider(context);
    testerWebViewProvider.setMessageHandler((msg) => handleWebviewCommand(msg, testerWebViewProvider));

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(viewId, testerWebViewProvider, {
            webviewOptions: {
                retainContextWhenHidden: true
            }
        }),
        vscode.languages.registerCodeLensProvider({ pattern: '**/*' }, new GenTestCodeLensProvider()),
        vscode.commands.registerCommand('intentionTest.show', () => {
            vscode.commands.executeCommand('workbench.view.extension.testerView');
        }),
        vscode.commands.registerCommand('intentionTest.generateTest',
            async (focalMethod: string, focalFile: string, projectAbsPath: string, focalFileAbsPath: string,) => {
                await vscode.commands.executeCommand('workbench.view.extension.testerView');
                // testerWebViewProvider.sendMessages();

                // const inputTestCaseName = await vscode.window.showInputBox({
                //     prompt: 'Enter the test case name',
                //     placeHolder: 'testSomeMethod'
                // });
                // if (!inputTestCaseName) {
                //     // vscode.window.showInformationMessage('Tester: Required to specify a test case name.');
                //     return;
                // }

                const inputDescriptionPrompt = `# Note: this description will become part of the prompt of ${ExtensionMetadata.TOOL_NAME}.\n# Enter the description, save it, then close the editor to start generation. Leave it empty for doing nothing.`;
                const inputDescriptionPlaceholder = `# Objective\n...\n\n# Preconditions\n1. ...\n# Expected Results\n1. ...\n\n${inputDescriptionPrompt}`;
                const firstLineSelection = new vscode.Range(
                    new vscode.Position(0, 0),
                    new vscode.Position(1, 0)
                );

                let inputTestCaseDescription = await showANewEditorForInput(inputDescriptionPlaceholder, firstLineSelection);
                inputTestCaseDescription = inputTestCaseDescription.replace(new RegExp(`\\n${inputDescriptionPrompt}$`), '');
                if (!inputTestCaseDescription) {
                    // vscode.window.showInformationMessage('Tester: Required to specify a test case description.');
                    return;
                }

                await generateTest(focalMethod, focalFile, inputTestCaseDescription, projectAbsPath, focalFileAbsPath, testerWebViewProvider);
            }
        ),
        vscode.commands.registerCommand('intentionTest.changeJunitVersion',
            async () => {
                const inputVersion = await vscode.window.showInputBox({
                    prompt: 'Enter the JUnit version',
                    placeHolder: '5'
                });
                if (!inputVersion) {
                    return;
                }

                const connectToPort = vscode.workspace.getConfiguration('intention-test').get('port');
                if (typeof connectToPort !== 'number') {
                    vscode.window.showErrorMessage('Tester: Port number is not set');
                    return;
                };

                const session = new TesterSession(
                    () => {},
                    (e) => {
                        vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
                    },
                    () => {},
                    connectToPort
                );

                session.changeJunitVersion(inputVersion);
            }
        ),
        virtualFileSystemRegister
    );
    setWebRoot(context.asAbsolutePath('web'));
}

async function generateTest(focalMethod: string, focalFile: string, testDesc: string, projectAbsPath: string, focalFileAbsPath: string, ui: TesterWebViewProvider): Promise<void> {
    const generateParams = {
        "target_focal_method": focalMethod,
        "target_focal_file": focalFile,
        "test_desc": testDesc,
        "project_path": projectAbsPath,
        "focal_file_path": focalFileAbsPath
    };
    const connectToPort = vscode.workspace.getConfiguration('intentionTest').get('port');
    if (typeof connectToPort !== 'number') {
        vscode.window.showErrorMessage('Tester: Port number is not set');
        return;
    };

    let prevMessages: any[] = [];
    let phase = 'init';
    const diffPlayer = new CodeHistoryDiffPlayer();

    const reactToNewMessages = async (messages: any[]) => {
        // start updating from first different message
        let _i = 0;
        for (; _i < prevMessages.length && _i < messages.length; _i++) {
            if (!(messages[_i].role === prevMessages[_i].role
                && messages[_i].content === prevMessages[_i].content)) {
                break;
            }
        }
        for (let i = _i; i < messages.length; i++) {
            phase = await updateMessage(messages[i], i, messages, ui, diffPlayer, phase);
        }
        await showWait(messages.at(-1), ui);
        prevMessages = messages;
    };

    const session = new TesterSession(
        (messages: string[]) => {
            reactToNewMessages(messages);
        },
        (e) => {
            vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
        },
        (junit_version) => {
            vscode.window.showInformationMessage('No referable test cases. Generating target test case without reference... JUnit version of ' + junit_version + ' is used. If you want to change the JUnit version, please use the command "IntentionTest: Change JUnit Version".');
        },
        connectToPort
    );
    activeSession = session;
    await sendSessionState(ui, 'running');
    await ui.showMessage({
        role: 'system-wait',
        content: 'Server is preparing...'
    });
    // await session.connect();
    try {
        await session.startQuery(generateParams, (e: any) => {
            vscode.window.showErrorMessage(`Query error when connecting to the server: ${e}`);
            // ui.showMessage({ cmd: 'error', message: 'an error has occurred'});
        });
    } finally {
        if (activeSession === session) {
            activeSession = undefined;
        }
        await sendSessionState(ui, 'idle');
    }
}

// TODO add blocking to prevent 2 sessions at the same time, or allow parallel sessions in new tab
// This function is for simulation
async function updateMessage(msg: any, i: number, allMsg: any, ui: TesterWebViewProvider, diffPlayer: CodeHistoryDiffPlayer, phase: string = 'init'): Promise<string> {
    const addTestCode = (test: string) => {
        const lang = detectCodeLang(test);
        const suffix = langSuffix(lang);
        // TODO extract the name of test, don't hardcode it
        diffPlayer.appendHistory(test, 'EmbeddedJettyFactoryTest', suffix, true);
    };

    let content = msg.content;
    // replace all line number in the form of [0-9]+: at the beginning of each line of any code block
    content = content.replace(/```.*?```/gs, (s: string) => {
        return s.replace(/^[0-9]+:/gm, '');
    });
    const senderType = msg.role === 'assistant' && msg.model
        ? `assistant (${msg.model})`
        : undefined;
    await ui.showMessage({
        role: msg.role,
        content: marked.parse(content),
        senderType
    });

    // show test code diff if matches
    let test;
    if (phase === 'init'
        && msg.role === 'user' && (test = extractRefTestCode(content))) {
        addTestCode(test);
        return 'after-ref';
    }
    else if (
        i > 0
        && allMsg[i - 1].role === 'user'
        && shouldGenTestPrompt(allMsg[i - 1].content)
        && (test = extractGenTestCode(content))
    ) {
        addTestCode(test);
    }
    return phase;
}

// TODO let backend determine the next step of what type to wait
async function showWait(msg: any, ui: TesterWebViewProvider): Promise<void> {
    // show wait
    const nextRole = msg.role === 'system'
        ? 'user'
        : (msg.role === 'user' ? 'assistant' : 'user');

    if (!(msg.content.trim().startsWith('FINISH GENERATION'))) {
        await ui.showMessage({
            role: nextRole + '-wait',
            content: 'Waiting...'
        });
    }
}

export function deactivate() { }

async function handleWebviewCommand(msg: any, ui: TesterWebViewProvider): Promise<void> {
    if (!(msg && msg.cmd)) {
        return;
    }
    if (msg.cmd === 'stop-run') {
        await stopActiveSession(ui);
    } else if (msg.cmd === 'clear-chat') {
        await ui.showMessage({ cmd: 'clear', toIndex: 0 });
    }
}

async function stopActiveSession(ui: TesterWebViewProvider): Promise<void> {
    if (!activeSession) {
        await sendSessionState(ui, 'idle');
        return;
    }
    try {
        await activeSession.stopActiveSession();
    } finally {
        activeSession = undefined;
    }
    await sendSessionState(ui, 'stopped', '生成已被手动停止。');
}

async function sendSessionState(
    ui: TesterWebViewProvider,
    state: 'idle' | 'running' | 'stopped',
    message?: string
): Promise<void> {
    await ui.showMessage({ cmd: 'session-state', state, message });
}
