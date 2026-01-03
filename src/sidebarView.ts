import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { detectCodeLang, extractGenTestCode, extractRefTestCode, isGenTestPrompt, langSuffix, shouldGenTestPrompt } from './textUtils';
import { CodeHistoryDiffPlayer } from './diffView';

let webRoot = '.';
const onlineResourceUrlPattern = '(?!http:\\/\\/|https:\\/\\/)([^"]*\\.[^"]+)';

export function setWebRoot(root: string) {
    webRoot = root;
}

export class TesterWebViewProvider implements vscode.WebviewViewProvider {
    private _context: vscode.ExtensionContext;
    private _view?: vscode.Webview;
    private _messageHandler?: (msg: any) => Thenable<void> | void;

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
            } else if (this._messageHandler) {
                await this._messageHandler(msg);
            }
        });

    }

    public setMessageHandler(handler: (msg: any) => Thenable<void> | void): void {
        this._messageHandler = handler;
    }

    private getHtmlContent(): string {
        const htmlPath = path.join(webRoot, 'index.html');
        return fs.readFileSync(htmlPath, 'utf8');
    }

    private getResolvedHtmlContent(): string {
        if (this._view) {
            // return this.getHtmlContent();
            return this.replaceUri(this.getHtmlContent(), this._view, onlineResourceUrlPattern);
        }
        else {
            return this.getHtmlContent();
        }
    }

    private replaceUri(html: string, webview: vscode.Webview, srcPattern: string): string {
        const cssFormattedHtml = html.replace(new RegExp(`(?<=href\="|src\=")${srcPattern}(?=")`, 'g'), (match, ...args) => {
            if (match) {
                const formattedCss = webview.asWebviewUri(vscode.Uri.file(path.join(webRoot, args[0])));
                return formattedCss.toString();
            }
            return "";
        });
    
        return cssFormattedHtml;
    }

    public async showMessage(message: any): Promise<void> {
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
