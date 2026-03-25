import { readFileSync } from 'fs';
import * as vscode from 'vscode';
import { requestDetailedDescription, TesterSession } from './client';
import { ExtensionMetadata } from './constants';
import { CodeHistoryDiffPlayer, virtualFileSystemRegister } from './diffView';
import { GenTestCodeLensProvider } from './inlineCodeLens';
import { customClientRequestHandler, saveGlobalContext } from './messageHandler';
import { setWebRoot, TesterWebViewProvider } from './sidebarView';
import { detectCodeLang, extractGenTestCode, extractRefTestCode, langSuffix } from './textUtils';
import { resolveWebviewOfflineResourceUri, showANewEditorForInput } from './utils';

export function activate(context: vscode.ExtensionContext): void {
    saveGlobalContext(context);

    let extensions = vscode.extensions.all;
    let themeExtensionPaths = extensions
        .filter(e => e.packageJSON.categories && e.packageJSON.categories.indexOf("Themes") != -1)
        .map(e => e.extensionPath);

    console.log("theme", themeExtensionPaths);

    const viewId = 'testView.sidebar';
    const testerWebViewProvider = new TesterWebViewProvider(context);

    context.subscriptions.push(
        vscode.commands.registerCommand('intentionTest.showDebugEditorWebview', () => {
            const debugWebviewRoot = context.asAbsolutePath('../dev/monaco-test/dist');

            const panel = vscode.window.createWebviewPanel(
                'catCoding',
                'Cat Coding',
                vscode.ViewColumn.One,
                {
                    enableScripts: true,
                    localResourceRoots: [vscode.Uri.file(debugWebviewRoot)]
                }
            );

            panel.webview.html = resolveWebviewOfflineResourceUri(readFileSync(`${debugWebviewRoot}/index.html`).toString(), panel.webview, debugWebviewRoot);
        })
    );

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

                let shortDescription = await vscode.window.showInputBox({
                    placeHolder: 'Please enter a short description. Remain empty to use the default template',
                    ignoreFocusOut: true
                });
                shortDescription = (shortDescription ?? '').trim();

                let inputDescriptionPlaceholder: string = '';
                if (shortDescription) {
                    const port = vscode.workspace.getConfiguration('intentionTest').get('port');
                    if (typeof port !== 'number') {
                        throw TypeError('Port value in configuration should be number');
                    }
                    inputDescriptionPlaceholder = await vscode.window.withProgress({
                        location: vscode.ProgressLocation.Notification,
                        title: "Suggesting a detailed description...",
                        cancellable: true
                    }, (progress, token) => {
                        let resolve: (s: string) => void;
                        const promise = new Promise<string>((_resolve) => { resolve = _resolve; });

                        requestDetailedDescription(port, focalMethod, shortDescription)
                            .then((result) => resolve(result));

                        token.onCancellationRequested((e) => resolve(''));

                        return promise;
                    });
                }

                if (!inputDescriptionPlaceholder) {
                    inputDescriptionPlaceholder = `# Objective\n...\n\n# Preconditions\n1. ...\n# Expected Results\n1. ...`;
                }

                const inputDescriptionPrompt = `# Note: this description will become part of the prompt of ${ExtensionMetadata.TOOL_NAME}.\n# Enter the description, save it, then close the editor to start generation. Leave it empty for doing nothing.`;
                inputDescriptionPlaceholder += `\n\n${inputDescriptionPrompt}`;
                
                const firstLineSelection = new vscode.Range(
                    new vscode.Position(0, 0),
                    new vscode.Position(0, 0)
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
        // TODO clear this, reuse the logic
        vscode.commands.registerCommand('intentionTest.changeJunitVersion',
            async () => {
                const inputVersion = await vscode.window.showInputBox({
                    prompt: 'Enter the JUnit version',
                    placeHolder: '5'
                });
                if (!inputVersion) {
                    return;
                }

                const connectToPort = vscode.workspace.getConfiguration('intentionTest').get('port');
                if (typeof connectToPort !== 'number') {
                    vscode.window.showErrorMessage('Tester: Port number is not set');
                    return;
                };

                const session = new TesterSession(
                    () => { },
                    () => { },
                    (e) => {
                        vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
                    },
                    () => { },
                    connectToPort
                );

                session.changeJunitVersion(inputVersion);
            }
        ),
        // TODO clear this, reuse the logic
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
                    () => { },
                    () => { },
                    (e) => {
                        vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
                    },
                    () => { },
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
    let processedMessageContent = new Map<string, string>(); // Track processed message content by ID
    const diffPlayer = new CodeHistoryDiffPlayer();

    const processNewMessages = async (messages: any[]) => {
        // Process only messages that haven't been processed before or have changed content
        for (let i = 0; i < messages.length; i++) {
            const message = messages[i];
            // Check if message has an ID
            if (message.id) {
                const previousContent = processedMessageContent.get(message.id);
                // Process if never seen before or content has changed
                if (previousContent !== message.content) {
                    processedMessageContent.set(message.id, message.content);
                    phase = await updateMessage(message, ui, diffPlayer, phase);
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
                    phase = await updateMessage(message, ui, diffPlayer, phase);
                }
            }
        }
        prevMessages = messages;
    };

    const processDeltaMessage = async (message: any) => {
        if (message.id && message.delta_content) {
            let previousContent = processedMessageContent.get(message.id);
            if (!previousContent) {
                processedMessageContent.set(message.id, previousContent = '');
            }
            
            processedMessageContent.set(message.id, previousContent + message.delta_content);
        }
    }

    const session = new TesterSession(
        processNewMessages,
        processDeltaMessage,
        (e) => {
            vscode.window.showErrorMessage(`Lost connection to the server: ${e}`);
        },
        (junit_version) => {
            vscode.window.showInformationMessage('No referable test cases. Generating target test case without reference... JUnit version of ' + junit_version + ' is used. If you want to change the JUnit version, please use the command "IntentionTest: Change JUnit Version".');
        },
        connectToPort,
        customClientRequestHandler
    );
    await ui.updateMessage({
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

// TODO this state-transfer / ui update / diff player update logic is totally messed up

// TODO add blocking to prevent 2 sessions at the same time, or allow parallel sessions in new tab
// This function is for simulation
async function updateMessage(msg: any, ui: TesterWebViewProvider, diffPlayer: CodeHistoryDiffPlayer, phase: string = 'init'): Promise<string> {
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
    content = content.replace(/```\n?(.*?)```/gs, (match: string, p1: string) => {     // some message may start with ```package
        return `\`\`\`java\n${p1}\`\`\``;
    });
    await ui.updateMessage({
        role: msg.role,
        content: content,
        id: msg.id // Pass through the message ID from server
    });

    // show test code diff if matches
    let test;
    if (test = extractRefTestCode(content)) {
        addTestCode(test);
        return 'after-ref';
    }
    else if (msg.role === 'assistant' && (test = extractGenTestCode(content))) {
        addTestCode(test);
    }
    return phase;
}

export function deactivate() { }
