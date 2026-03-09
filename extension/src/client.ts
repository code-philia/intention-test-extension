// create a python subprocess and communicate with it through network
import { request, RequestOptions } from 'http';

export class TesterSession {
    private updateMessageCallback?: (...args: any[]) => any;
    private errorCallback?: (...args: any[]) => any;
    private showNoRefMsg?: (...args: any[]) => any;
    private clientRequestHandler?: (requestData: any) => Promise<string>;
    private connectToPort: number;
    private currentSessionId?: string;
    
    // setting connectToPort to 0 to start up an internal server
    constructor(
        updateMessageCallback?: (...args: any[]) => any, 
        errorCallback?: (...args: any[]) => any, 
        showNoRefMsg?: (...args: any[]) => any, 
        connectToPort: number = 0,
        clientRequestHandler?: (requestData: any) => Promise<string>
    ) {
        this.updateMessageCallback = updateMessageCallback;
        this.errorCallback = errorCallback;
        this.showNoRefMsg = showNoRefMsg;
        this.connectToPort = connectToPort;
        this.clientRequestHandler = clientRequestHandler;
    }

    private async makeHttpRequest(path: string, data: any): Promise<any> {
        const requestBody = JSON.stringify(data);
        const requestData = new TextEncoder().encode(requestBody);

        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: path,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': requestData.length.toString()
            }
        };

        return new Promise((resolve, reject) => {
            const req = request(options, (res) => {
                let responseBody = '';

                res.on('data', (chunk) => {
                    responseBody += chunk.toString();
                });

                res.on('end', () => {
                    if (res.statusCode === 200) {
                        try {
                            const parsedResponse = JSON.parse(responseBody);
                            resolve(parsedResponse);
                        } catch (e) {
                            resolve(responseBody);
                        }
                    } else {
                        reject(new Error(`HTTP ${res.statusCode}: ${responseBody}`));
                    }
                });

                res.on('error', (e) => {
                    reject(e);
                });
            });

            req.on('error', (e) => {
                reject(e);
            });

            req.write(requestData);
            req.end();
        });
    }

    async changeJunitVersion(version: string): Promise<void> {
        try {
            await this.makeHttpRequest('/junitVersion', { 
                type: 'change_junit_version', 
                data: version 
            });
        } catch (error) {
            console.error('Failed to change JUnit version:', error);
            throw error;
        }
    }

    async sendClientResponse(sessionId: string, requestId: string, response: string): Promise<void> {
        const responseData = {
            session_id: sessionId,
            request_id: requestId,
            response: response
        };

        try {
            const result = await this.makeHttpRequest('/response', responseData);
            console.log('Client response sent successfully:', result);
        } catch (error) {
            console.error('Failed to send client response:', error);
            throw error;
        }
    }

    private async handleClientRequest(requestData: any): Promise<void> {
        console.log('Received client request data:', requestData);
        
        const { session_id, request_id, prompt, response_type, options } = requestData;

        console.log('Server requesting client input:', {
            session_id,
            request_id,
            prompt,
            response_type,
            options
        });

        try {
            let userResponse: string;

            if (this.clientRequestHandler) {
                // Use custom handler if provided
                userResponse = await this.clientRequestHandler(requestData);
            } else {
                // Default handling based on response type
                userResponse = await this.getDefaultResponse(response_type, prompt, options);
            }

            // Send response back to server
            await this.sendClientResponse(session_id, request_id, userResponse);

        } catch (error) {
            console.error('Error handling client request:', error);
            // Send a default response on error to prevent server timeout
            await this.sendClientResponse(session_id, request_id, '').catch(e => 
                console.error('Failed to send error response:', e)
            );
        }
    }

    private async getDefaultResponse(responseType: string, prompt: string, options: string[]): Promise<string> {
        switch (responseType) {
            case 'confirm':
                // Default to 'yes' for confirmations
                return 'yes';
                
            case 'choice':
                // Default to first option if available, otherwise empty
                return options && options.length > 0 ? options[0] : '';
                
            case 'text':
                // Return a default text response
                return 'Default response from TypeScript client';
                
            default:
                console.warn('Unknown response type:', responseType);
                return '';
        }
    }

    async startQuery(args: any, cancelCb: (e: any) => any): Promise<void> {
        const requestData = new TextEncoder().encode(JSON.stringify({ type: 'query', data: args }) + '\n');

        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: '/session',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': requestData.length.toString()
            }
        };

        return new Promise((resolve, reject) => {
            const req = request(options, (res) => {
                if (res.statusCode !== 200) {
                    reject(new Error(`HTTP ${res.statusCode}: Failed request from server`));
                    return;
                }

                let status = 'before-start';
                let buffer = '';
                let hasResolved = false;

                res.on('data', (chunk) => {
                    try {
                        buffer += chunk.toString();
                        
                        // Process complete messages (assuming messages are line-delimited)
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || ''; // Keep incomplete line in buffer

                        for (const line of lines) {
                            if (line.trim()) {
                                this.processMessage(line.trim(), status, 
                                    () => {
                                        if (!hasResolved && status === 'before-start') {
                                            hasResolved = true;
                                            status = 'started';
                                            resolve();
                                        }
                                    }, 
                                    reject, 
                                    cancelCb
                                );
                            }
                        }
                    } catch (e) {
                        console.error('Error processing streaming data:', e);
                        cancelCb(e);
                    }
                });

                res.on('end', () => {
                    console.log('Stream ended');
                    resolve();
                });

                res.on('error', (e) => {
                    console.error('Stream error:', e);
                    reject(e);
                });
            });

            req.on('error', (e) => {
                console.error('Request error:', e);
                reject(e);
            });

            req.write(requestData);
            req.end();
        });
    }

    private processMessage(
        line: string, 
        status: string, 
        resolve: (value?: any) => void, 
        reject: (reason?: any) => void, 
        cancelCb: (e: any) => any
    ): void {
        try {
            // Handle different message formats
            let msg: any;
            
            if (line.startsWith('data: ')) {
                // Server-Sent Events format
                const jsonStr = line.substring(6); // Remove 'data: ' prefix
                msg = JSON.parse(jsonStr);
            } else if (line.startsWith('{')) {
                // Direct JSON format
                msg = JSON.parse(line);
            } else {
                console.log('Non-JSON message:', line);
                return;
            }

            console.log('Received message:', msg);

            if (status === 'before-start') {
                // Confirm start
                if (msg.type === 'status' && msg.data?.status === 'start') {
                    console.log('Session started successfully');
                    if (msg.data.session_id) {
                        this.currentSessionId = msg.data.session_id;
                    }
                    resolve();
                } else {
                    reject(new TypeError('Failed to receive start message'));
                }
            } else {
                // Process streaming messages
                this.handleStreamingMessage(msg);
            }

        } catch (e) {
            console.error('Error parsing message:', line, e);
            cancelCb(e);
        }
    }

    private handleStreamingMessage(msg: any): void {
        if (!msg.type || !msg.data) {
            throw new TypeError('Invalid message format');
        }

        switch (msg.type) {
            case 'msg':
                if (msg.data.session_id && msg.data.messages) {
                    if (this.updateMessageCallback) {
                        this.updateMessageCallback(msg.data.messages);
                    }
                }
                break;

            case 'noreference':
                if (msg.data.session_id) {
                    const junit_version = msg.data.junit_version;
                    if (this.showNoRefMsg) {
                        this.showNoRefMsg(junit_version);
                    }
                }
                break;

            case 'client_request':
                if (msg.data.session_id) {
                    this.handleClientRequest(msg.data).catch(error => {
                        console.error('Error handling client request:', error);
                        if (this.errorCallback) {
                            this.errorCallback(error);
                        }
                    });
                }
                break;

            default:
                console.warn('Unknown message type:', msg.type);
        }
    }

    public closeConnection(): void {
        console.log('Closing session connection');
        this.currentSessionId = undefined;
        // Note: HTTP streaming connections are closed by the server when session ends
    }
}
