import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { closeTab, findDiffTab, getActiveTab } from './utils';

const utf8Encoder = new TextEncoder();

type VirtualFile = {
    stat: vscode.FileStat;
    bytes: Uint8Array;
};

type CodeFile = {
    name: string;
    suffix: string;     // suffix like '.java'
    content: string;    // content of code
};

class VirtualNamedFileSystemProvider implements vscode.FileSystemProvider {
    onDidChangeFile: vscode.Event<vscode.FileChangeEvent[]>;
    _changeEvent: vscode.EventEmitter<vscode.FileChangeEvent[]>;
    private files: Map<string, VirtualFile> = new Map();

    private static readonly scheme: string = 'temp';

    constructor() {
        this._changeEvent = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
        this.onDidChangeFile = this._changeEvent.event;
    }
    setFileForId(id: string, file: VirtualFile): void {
        this.files.set(id, file);
    }
    getFileFromId(id: string): VirtualFile | undefined {
        return this.files.get(id);
    }
    getFileFromUri(uri: vscode.Uri): VirtualFile | undefined{
        const id = this.uriToId(uri);
        return id ? this.getFileFromId(id) : undefined;
    }
    idToPath(id: string): string {
        return `/${id}`;
    }
    idToUri(id: string): vscode.Uri {
        return vscode.Uri.parse(`${VirtualNamedFileSystemProvider.scheme}:${this.idToPath(id)}`);
    }
    pathToId(path: string): string | undefined {
        if (path.startsWith('/')) {
            return path.substring(1);
        }
        return undefined;
    }
    uriToId(uri: vscode.Uri): string {      // FIXME this is unsafe
        return decodeURIComponent(uri.toString()).slice('temp:/'.length);
    }
    notifyUpdateId(...ids: string[]): void {
        this._changeEvent.fire(ids.map(id => {
            return {
                type: vscode.FileChangeType.Changed,
                uri: this.idToUri(id)
            };
        }));
    }

    // standard interface
    watch(uri: vscode.Uri, options: { readonly recursive: boolean; readonly excludes: readonly string[]; }): vscode.Disposable {
        return { dispose: (): void => { } };
    }
    stat(uri: vscode.Uri): vscode.FileStat | Thenable<vscode.FileStat> {
        const stat = this.getFileFromUri(uri)?.stat;
        if (stat) {
            return stat;
        } else {
            const newFileStat = {
                type: vscode.FileType.File,
                size: 0,
                ctime: Date.now(),
                mtime: Date.now()
            };
            this.files.set(this.uriToId(uri), {
                stat: newFileStat,
                bytes: new Uint8Array(0)
            });
            return newFileStat;
        }
    }
    readDirectory(uri: vscode.Uri): [string, vscode.FileType][] | Thenable<[string, vscode.FileType][]> {
        throw new Error('Method not implemented.');
    }
    createDirectory(uri: vscode.Uri): void | Thenable<void> {
        throw new Error('Method not implemented.');
    }
    readFile(uri: vscode.Uri): Uint8Array | Thenable<Uint8Array> {
        const content= this.getFileFromUri(uri)?.bytes;
        if (content) {
            return content;
        }
        throw vscode.FileSystemError.FileNotFound(uri);
    }
    writeFile(uri: vscode.Uri, content: Uint8Array, options: { readonly create: boolean; readonly overwrite: boolean; }): void | Thenable<void> {
        const file = this.getFileFromUri(uri);
        if (file) {
            file.bytes = content.slice();
        } else {
            this.files.set(this.uriToId(uri), {
                stat: {
                    type: vscode.FileType.File,
                    size: content.length,
                    ctime: Date.now(),
                    mtime: Date.now()
                },
                bytes: content.slice()
            });
        }
    }
    delete(uri: vscode.Uri, options: { readonly recursive: boolean; }): void | Thenable<void> {
        this.files.delete(this.uriToId(uri));
    }
    rename(oldUri: vscode.Uri, newUri: vscode.Uri, options: { readonly overwrite: boolean; }): void | Thenable<void> {
        throw new Error('Method not implemented.');
    }
    
}

const virtualFileSystem = new VirtualNamedFileSystemProvider();
export const virtualFileSystemRegister = vscode.workspace.registerFileSystemProvider('temp', virtualFileSystem, {
    isCaseSensitive: true
});

export class CodeHistoryDiffPlayer implements vscode.Disposable {
    sessionId: string;
    history: CodeFile[];
    diffTab?: vscode.Tab;

    constructor() {
        this.sessionId = crypto.createHash('sha256').update(Date.now().toString()).digest('hex');
        this.history = [];
    }

    get length(): number {
        return this.history.length;
    }

    private labelOfIndex(idx: number) {
        return idx <= 0 ? 'Ref' : `Gen-${idx}`;
    }

    private createFile(content: string) {
        const bytesContent = utf8Encoder.encode(content);
        const file: VirtualFile = {
            stat: {
                type: vscode.FileType.File,
                size: bytesContent.length,
                ctime: Date.now(),
                mtime: Date.now(),
                permissions: vscode.FilePermission.Readonly
            },
            bytes: bytesContent
        };
        return file;
    }

    appendHistory(code: string, name: string, lang: string, showNext: boolean = true): void {
        this.history.push({
            name: name,
            suffix: lang,
            content: code
        });
        if (showNext) {
            this.showDiffAt(this.length - 2);
        }
    }

    async showDiffAt(idx: number): Promise<void> {
        if (this.length < 2) {
            return;
        }
        idx = Math.max(0, Math.min(idx, this.length - 2));
        
        // Align to the language suffix of the new content
        const leftId = `${this.history[idx + 1].name}${this.history[idx + 1].suffix}?id=${this.sessionId}&rank=0`;
        const rightId = `${this.history[idx + 1].name}${this.history[idx + 1].suffix}?id=${this.sessionId}&rank=1`;
        const leftFile = this.createFile(this.history[idx].content);
        const rightFile = this.createFile(this.history[idx + 1].content);
        virtualFileSystem.setFileForId(leftId, leftFile);
        virtualFileSystem.setFileForId(rightId, rightFile);
        
        // Close the existing diff tab if it is open
        let tab;
        if (this.diffTab && (tab = getActiveTab(this.diffTab))) {
            await closeTab(tab);
        }
        
        // Execute the diff command and await its completion
        await vscode.commands.executeCommand(
            'vscode.diff',
            virtualFileSystem.idToUri(leftId),
            virtualFileSystem.idToUri(rightId),
            `${this.labelOfIndex(idx)} → ${this.labelOfIndex(idx + 1)}`
        );
        
        // Update the diffTab reference
        this.diffTab = findDiffTab(virtualFileSystem.idToUri(leftId), virtualFileSystem.idToUri(rightId));
        
        // Notify the virtual file system about the update
        virtualFileSystem.notifyUpdateId(leftId, rightId);
    }

    // TODO add disposal when test generation session ends
    dispose(): void {
        if (this.diffTab) {
            closeTab(this.diffTab);
        }
    }
}
