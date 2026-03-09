import Parser from 'tree-sitter';
import JavaLanguage from 'tree-sitter-java';

const javaParser = new Parser();
javaParser.setLanguage(JavaLanguage);

export function isGenTestPrompt(msg: string): boolean {
    return msg.includes('Instruction for this step:');
}

export function isCodeQLPrompt(msg: string): boolean {
    return msg.startsWith('The required');
}

export function shouldGenTestPrompt(msg: string): boolean {
    return isGenTestPrompt(msg) || isCodeQLPrompt(msg);
}

export function extractRefTestCode(msg: string): string | undefined {
    // keep the last line break of code
    const m = msg.match(/# Referable Test Case\n```(.*?)(?<=\n)```/s);
    return m?.[1];
}

export function extractGenTestCode(msg: string): string | undefined {
    // keep the last line break of code
    const m = msg.match(/```\n(.*?)(?<=\n)```/s);
    if (m && !(m[1].trim().startsWith('# QUERY:'))) {
        return m[1];
    }
    return undefined;
}

export function detectCodeLang(code: string): string {
    return 'java';
}

export function langSuffix(lang: string): string {
    if (lang === 'java') {
        return '.java';
    }
    return '';
}

export function extractMethods(text: string, lang?: string): [number, string][] | undefined {
    // return which lines and corresponding method declarations
    // only supporting Java now
    if (lang !== 'java') {
        return undefined;
    }
    const root = javaParser.parse(text).rootNode;
    const methods: [number, string][] = [];
    const cursor = root.walk();
    const walk = (cursor: Parser.TreeCursor, cb: (node: Parser.SyntaxNode) => any) => {
        if (cursor.gotoFirstChild()) {
            while (true) {
                cb(cursor.currentNode);
                walk(cursor, cb);
                if (!cursor.gotoNextSibling()) {
                    break;
                }
            }
            cursor.gotoParent();
        }
    };

    walk(cursor, (node) => {
        if (node && node.type === 'method_declaration') {
            methods.push([node.startPosition.row, node.text]);
        }
    });
    return methods;
}
