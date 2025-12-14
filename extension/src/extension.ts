import * as vscode from 'vscode';
import { TesterSession } from './client';
import { ExtensionMetadata } from './constants';
import { CodeHistoryDiffPlayer, virtualFileSystemRegister } from './diffView';
import { GenTestCodeLensProvider } from './inlineCodeLens';
import { customClientRequestHandler } from './messageHandler';
import { setWebRoot, TesterWebViewProvider } from './sidebarView';
import { detectCodeLang, extractGenTestCode, extractRefTestCode, langSuffix, shouldGenTestPrompt } from './textUtils';
import { showANewEditorForInput } from './utils';

export function activate(context: vscode.ExtensionContext): void {
    const viewId = 'testView.sidebar';
    const testerWebViewProvider = new TesterWebViewProvider(context);

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
        vscode.commands.registerCommand('intentionTest.generateCoverageAndDescription',
            async () => {
                const workspaceFolders = vscode.workspace.workspaceFolders;
                if (!workspaceFolders || workspaceFolders.length === 0) {
                    vscode.window.showErrorMessage('No workspace folder open');
                    return;
                }
                const projectPath = workspaceFolders[0].uri.fsPath;

                const connectToPort = vscode.workspace.getConfiguration('intentionTest').get('port');
                if (typeof connectToPort !== 'number') {
                    vscode.window.showErrorMessage('Tester: Port number is not set');
                    return;
                };

                const enableJacoco = vscode.workspace.getConfiguration('intentionTest').get('enableJacoco', false);
                const testSuffix = vscode.workspace.getConfiguration('intentionTest').get('testSuffix', 'Test');

                const session = new TesterSession(
                    () => {},
                    (e) => {
                        vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
                    },
                    () => {},
                    connectToPort
                );

                vscode.window.withProgress({
                    location: vscode.ProgressLocation.Notification,
                    title: "Generating coverage and test description...",
                    cancellable: false
                }, async (progress) => {
                    try {
                        await session.generateCoverageAndDescription(projectPath, enableJacoco, testSuffix);
                        vscode.window.showInformationMessage('Successfully generated coverage and test description.');
                    } catch (e) {
                        vscode.window.showErrorMessage(`Failed to generate data: ${e}`);
                    }
                });
            }
        ),
        virtualFileSystemRegister
    );
    setWebRoot(context.asAbsolutePath('../web/dist'));
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
    let processedMessageIds = new Set<string>(); // Track processed message IDs
    let processedMessageContent = new Map<string, string>(); // Track processed message content by ID
    const diffPlayer = new CodeHistoryDiffPlayer();

    const reactToNewMessages = async (messages: any[]) => {
        // Process only messages that haven't been processed before or have changed content
        for (let i = 0; i < messages.length; i++) {
            const message = messages[i];
            // Check if message has an ID
            if (message.id) {
                const previousContent = processedMessageContent.get(message.id);
                // Process if never seen before or content has changed
                if (!processedMessageIds.has(message.id) || previousContent !== message.content) {
                    processedMessageIds.add(message.id);
                    processedMessageContent.set(message.id, message.content);
                    phase = await updateMessage(message, i, messages, ui, diffPlayer, phase);
                }
            } else {
                // For messages without ID, use the old comparison logic as fallback
                let shouldProcess = true;
                if (i < prevMessages.length) {
                    if (messages[i].role === prevMessages[i].role && 
                        messages[i].content === prevMessages[i].content) {
                        shouldProcess = false;
                    }
                }
                if (shouldProcess) {
                    phase = await updateMessage(message, i, messages, ui, diffPlayer, phase);
                }
            }
        }
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
        connectToPort,
        customClientRequestHandler
    );
    await ui.showMessage({
        role: 'system-wait',
        content: 'Server is preparing...'
    });
    // await session.connect();
    await session.startQuery(generateParams, (e: any) => {
        vscode.window.showErrorMessage(`Query error when connecting to the server: ${e}`);
        console.error('Query error when connecting to the server: ', e.stack);
        // ui.showMessage({ cmd: 'error', message: 'an error has occurred'});
    });
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
    content = content.replace(/```(.*?)```/gs, (match: string, p1: string) => {
        return `\`\`\`java${p1}\`\`\``;
    });
    await ui.showMessage({
        role: msg.role,
        content: content,
        id: msg.id // Pass through the message ID from server
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

export function deactivate() { }


