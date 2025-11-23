import { readFileSync } from 'fs';
import { join as joinPath } from 'path';
import * as vscode from 'vscode';

type Input = vscode.TabInputText | vscode.TabInputTextDiff
    | vscode.TabInputCustom | vscode.TabInputWebview | vscode.TabInputNotebook
    | vscode.TabInputNotebookDiff | vscode.TabInputTerminal | unknown;

export async function closeTab(tab: vscode.Tab): Promise<boolean> {
    return await vscode.window.tabGroups.close(tab);
}

function matchInAllTabs(cri: (tab: vscode.Tab, ...args: any[]) => boolean): vscode.Tab | undefined {
    for (const tabGroup of vscode.window.tabGroups.all) {
        for (const existingTab of tabGroup.tabs) {
            if (cri(existingTab)) {
                return existingTab;
            }
        }
    }
    return undefined;
}

export function getActiveTab(tab: vscode.Tab): vscode.Tab | undefined {
    return matchInAllTabs((_tab) => _tab === tab);
}

export function getActiveTabForInput(input: Input): vscode.Tab | undefined {
    return matchInAllTabs((_tab) => _tab.input === input);
}

export function findDiffTab(oldUri: vscode.Uri, newUri: vscode.Uri): vscode.Tab | undefined {
    return matchInAllTabs((_tab) => {
        const input = _tab.input;
        if (!(input instanceof vscode.TabInputTextDiff)) {
            return false;
        }
        return input.original.toString() === oldUri.toString() && input.modified.toString() === newUri.toString();
    });
}

/**
 * Show a new text editor to collect user input for
 * new-lineable text, just like Git commit message.
 * 
 * This relies on the virtual filesystem of scheme 'temp'.
 */
export async function showANewEditorForInput(placeholderText?: string, selection?: vscode.Range): Promise<string> {
    const tempScheme = 'temp';
    // const tempUri = vscode.Uri.parse(`${tempScheme}:/input-${Date.now()}`);
    const tempUri = vscode.Uri.parse(`${tempScheme}:/description-input`);
    const newTabLabel = 'Test Description';

    if (placeholderText) {
        const encoder = new TextEncoder();
        await vscode.workspace.fs.writeFile(tempUri, encoder.encode(placeholderText));
    }

    vscode.commands.executeCommand(
        'vscode.open',
        tempUri,
        selection ? { selection } : undefined,
        newTabLabel
    );

    const cb = new Promise<string>((res) => {
        const disposable = vscode.workspace.onDidCloseTextDocument(doc => {
            if (doc.uri.toString() === tempUri.toString()) {
                res(doc.getText());
                vscode.workspace.fs.delete(tempUri);
                disposable.dispose();
            }
        });
    });

    return cb;
}

export function getExtensionResource(context: vscode.ExtensionContext, relativePath: string): string {
    return context.asAbsolutePath(joinPath('resources', relativePath));
}

export function getExtensionResourceText(context: vscode.ExtensionContext, relativePath: string): string {
    const resourcePath = getExtensionResource(context, relativePath);
    return readFileSync(resourcePath, 'utf8');
}
