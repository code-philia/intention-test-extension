// Example usage of the enhanced TesterSession with client response handling

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

// Enhanced custom client request handler with file selection support
export async function customClientRequestHandler(requestData: any): Promise<string> {
    const { prompt, response_type, options } = requestData;

    switch (response_type) {
        case 'confirm':
            // Show a VS Code confirmation dialog
            const confirmResult = await vscode.window.showInformationMessage(
                prompt,
                { modal: true },
                'Yes',
                'No'
            );
            return confirmResult === 'Yes' ? 'yes' : 'no';

        case 'choice':
            // Show a VS Code quick pick
            const choiceResult = await vscode.window.showQuickPick(
                options,
                {
                    placeHolder: prompt,
                    canPickMany: false
                }
            );
            return choiceResult || options[0] || '';

        case 'text':
            // Check if this is a request for a test case file
            if (prompt.toLowerCase().includes('reference test case') || 
                prompt.toLowerCase().includes('test case')) {
                return await handleTestCaseRequest(prompt);
            } else {
                // Show a VS Code input box for regular text
                const textResult = await vscode.window.showInputBox({
                    prompt: prompt,
                    placeHolder: 'Enter your response...'
                });
                return textResult || '';
            }

        default:
            return '';
    }
}

// Specialized handler for test case requests
async function handleTestCaseRequest(prompt: string): Promise<string> {
    // First, ask the user how they want to provide the test case
    const provideMethod = await vscode.window.showQuickPick(
        [
            'Select a test case file',
            'Paste test case content', 
            'Skip (no reference test case)',
            'Search workspace for test files'
        ],
        {
            placeHolder: 'How would you like to provide the reference test case?',
            canPickMany: false
        }
    );

    switch (provideMethod) {
        case 'Select a test case file':
            return await selectTestCaseFile();
            
        case 'Paste test case content':
            return await pasteTestCaseContent();
            
        case 'Search workspace for test files':
            return await searchAndSelectTestFile();
            
        case 'Skip (no reference test case)':
        default:
            return '';
    }
}

// Function to select a test case file using file dialog
async function selectTestCaseFile(): Promise<string> {
    const fileUri = await vscode.window.showOpenDialog({
        canSelectFiles: true,
        canSelectFolders: false,
        canSelectMany: false,
        filters: {
            'Java Test Files': ['java'],
            'All Files': ['*']
        },
        openLabel: 'Select Test Case File'
    });

    if (fileUri && fileUri[0]) {
        try {
            const filePath = fileUri[0].fsPath;
            const content = fs.readFileSync(filePath, 'utf8');
            
            // Validate it looks like a test file
            if (isValidTestCase(content)) {
                vscode.window.showInformationMessage(`Test case loaded from: ${path.basename(filePath)}`);
                return content;
            } else {
                vscode.window.showWarningMessage('Selected file does not appear to be a valid test case.');
                return '';
            }
        } catch (error) {
            vscode.window.showErrorMessage(`Error reading file: ${error}`);
            return '';
        }
    }
    
    return '';
}

// Function to let user paste test case content
async function pasteTestCaseContent(): Promise<string> {
    const content = await vscode.window.showInputBox({
        prompt: 'Paste your reference test case content here:',
        placeHolder: '@Test\npublic void testExample() {\n    // test code here\n}'
    });

    if (content && isValidTestCase(content)) {
        vscode.window.showInformationMessage('Test case content received.');
        return content;
    } else if (content) {
        vscode.window.showWarningMessage('Content does not appear to be a valid test case.');
    }
    
    return '';
}

// Function to search workspace for test files
async function searchAndSelectTestFile(): Promise<string> {
    try {
        // Search for Java files that look like test files
        const testFiles = await vscode.workspace.findFiles(
            '**/*Test*.java',  // Pattern for test files
            '**/node_modules/**',  // Exclude node_modules
            50  // Limit results
        );

        if (testFiles.length === 0) {
            vscode.window.showInformationMessage('No test files found in workspace.');
            return '';
        }

        // Create quick pick items
        const quickPickItems = testFiles.map(uri => ({
            label: path.basename(uri.fsPath),
            description: vscode.workspace.asRelativePath(uri),
            detail: uri.fsPath,
            uri: uri
        }));

        const selectedItem = await vscode.window.showQuickPick(quickPickItems, {
            placeHolder: 'Select a test file from your workspace',
            matchOnDescription: true,
            matchOnDetail: true
        });

        if (selectedItem) {
            try {
                const content = fs.readFileSync(selectedItem.uri.fsPath, 'utf8');
                
                if (isValidTestCase(content)) {
                    vscode.window.showInformationMessage(`Test case loaded: ${selectedItem.label}`);
                    return content;
                } else {
                    vscode.window.showWarningMessage(`File ${selectedItem.label} does not appear to be a valid test case.`);
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Error reading ${selectedItem.label}: ${error}`);
            }
        }
    } catch (error) {
        vscode.window.showErrorMessage(`Error searching for test files: ${error}`);
    }
    
    return '';
}

// Helper function to validate if content looks like a test case
function isValidTestCase(content: string): boolean {
    if (!content || !content.trim()) {
        return false;
    }

    const testIndicators = [
        '@Test',
        'public void test',
        'public class',
        'import org.junit',
        'junit.framework',
        'Assert.',
        'assertEquals',
        'assertTrue',
        'assertFalse'
    ];

    return testIndicators.some(indicator => content.includes(indicator));
}
