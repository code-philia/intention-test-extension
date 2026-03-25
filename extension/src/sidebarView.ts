import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resolveWebviewOfflineResourceUri } from './utils';

let webRoot = '.';

export function setWebRoot(root: string) {
    webRoot = root;
}

export class TesterWebViewProvider implements vscode.WebviewViewProvider {
    private _context: vscode.ExtensionContext;
    private _view?: vscode.Webview;

    constructor(context: vscode.ExtensionContext) {
        this._context = context;
    }

    resolveWebviewView(webviewView: vscode.WebviewView): void {
        this._view = webviewView.webview;

        webviewView.webview.options = {
            enableScripts: true
        };

        webviewView.webview.options = getDefaultWebviewOptions();
        webviewView.webview.html = this.getResolvedHtmlContent();

        this._view?.onDidReceiveMessage(async (msg) => {
            if (msg.cmd === 'open-code' && msg.content && msg.lang) {
            const doc = await vscode.workspace.openTextDocument({ language: msg.lang, content: msg.content });
            vscode.window.showTextDocument(doc);
            }
        });
    }

    private getHtmlContent(): string {
        const htmlPath = path.join(webRoot, 'index.html');
        return fs.readFileSync(htmlPath, 'utf8');
    }

    private getResolvedHtmlContent(): string {
        if (this._view) {
            return resolveWebviewOfflineResourceUri(this.getHtmlContent(), this._view, webRoot);
        }
        else {
            return this.getHtmlContent();
        }
    }

    public async updateMessage(message: any): Promise<void> {
        this._view?.postMessage(message);
    }
}

function getDefaultWebviewOptions(): vscode.WebviewOptions {
	const resourceUri = vscode.Uri.file(webRoot);
	return {
		"enableScripts": true,
		"localResourceRoots": [
			resourceUri
		]
	};
}
