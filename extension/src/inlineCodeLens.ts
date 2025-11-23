import * as vscode from 'vscode';
import { extractMethods } from './textUtils';

export class GenTestCodeLensProvider implements vscode.CodeLensProvider {
    provideCodeLenses(document: vscode.TextDocument, token: vscode.CancellationToken): vscode.CodeLens[] {
        const codeLensLines: [number, string][] = extractMethods(document.getText(), 'java') || [];
        
        const codeLensesInfo = codeLensLines.map((info) => {
            const [lineNo, method] = info;
            if (vscode.workspace.workspaceFolders === undefined) {
                vscode.window.showInformationMessage('Tester: No workspace folder is detected.');
            } else {
                const methodGenerateTestCommand = {
                    title: 'Generate Test\u2002$(test-tube)',   // NOTE white space between text and icon is omitted in the new version of VS Code
                    command: 'intentionTest.generateTest',
                    // test name is to be input later
                    arguments: [
                        method,
                        document.getText(),
                        vscode.workspace.workspaceFolders[0].uri.fsPath,
                        document.fileName
                    ]
                };
                return {
                    range: new vscode.Range(lineNo, 0, lineNo, 0),
                    command: methodGenerateTestCommand,
                    isResolved: true
                };
            }
        });

        return codeLensesInfo.filter((info) => info !== undefined);
    }
}
