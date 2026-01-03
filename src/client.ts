// create a python subprocess and communicate with it through network
import { request, RequestOptions, ClientRequest } from 'http';

export class TesterSession {
    private updateMessageCallback?: (...args: any[]) => any;
    private errorCallbcak?: (...args: any[]) => any;
    private showNoRefMsg?: (...args: any[]) => any;
    private connectToPort: number;
    private currentRequest?: ClientRequest;
    private finishActiveRequest?: () => void;
    private isCancelling = false;
    private activeSessionId?: string;
    
    // setting connectToPort to 0 to start up an internal server
    constructor(updateMessageCallback?: (...args: any[]) => any, errorCallback?: (...args: any[]) => any, showNoRefMsg?: (...args: any[]) => any, connectToPort: number = 0) {
        this.updateMessageCallback = updateMessageCallback;
        this.errorCallbcak = errorCallback;
        this.showNoRefMsg = showNoRefMsg;
        this.connectToPort = connectToPort;
    }

    async changeJunitVersion(version: string) {
        const requestData = new TextEncoder().encode(JSON.stringify({ type: 'change_junit_version', data: version }) + '\n');

        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: '/junitVersion',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': requestData.length.toString()
            }
        };

        let finish: (value?: any) => void;
        const finishePromise = new Promise((res, rej) => { finish = res; });
        
        const req = request(options, (res) => {
            if (res.statusCode !== 200) {
                throw new Error('Failed request from server.');
            }

            res.on('error', (e) => {
                console.error(e);
            });
        });

        req.on('error', (e) => {
            console.error(`Problem on request: ${e}`);
        });

        req.write(requestData);
        req.end();
        await finishePromise;
    }

    async startQuery(args: any, cancelCb: (e: any) => any) {
        const requestData = new TextEncoder().encode(JSON.stringify({ type: 'query', data: args }) + '\n');
        this.activeSessionId = undefined;

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

        let finish: (value?: any) => void;
        const finishePromise = new Promise<void>((res) => { finish = res; });
        this.finishActiveRequest = () => {
            finish();
            this.resetRequestState();
        };
        this.isCancelling = false;
        const req = request(options, (res) => {
            let status = 'before-start';

            if (res.statusCode !== 200) {
                throw new Error('Failed request from server.');
            }

            res.on('data', (chunk) => {
                try {
                    const msg = JSON.parse(chunk.toString());
                    if (status === 'before-start') {
                        // confirm start
                        if (!(msg.type && msg.data && msg.type === 'status' && msg.data.status === 'start')) {
                            throw TypeError('Failed to receive start message');
                        }
                        this.activeSessionId = msg.data.session_id;
                        status = 'started';
                    } else if (status !== 'finished') {
                        // receive messages
                        if (msg.type && msg.data) {
                            if (msg.type === 'status' && msg.data.status === 'finish') {
                                status = 'finished';
                                this.activeSessionId = undefined;
                                this.finishActiveRequest?.();
                                return;
                            } else if (msg.type === 'msg' && msg.data.session_id && msg.data.messages) {
                                if (this.updateMessageCallback) {
                                    this.updateMessageCallback(msg.data.messages);
                                }
                            } else if (msg.type === 'noreference' && msg.data.session_id) {
                                const junit_version = msg.data.junit_version;
                                if (this.showNoRefMsg) {
                                    this.showNoRefMsg(junit_version);
                                }
                            } else {
                                throw TypeError('Invalid message type');
                            }
                        } else {
                            throw TypeError('Invalid message format');
                        }
                        console.log(msg);
                    }
                    
                } catch (e) {
                    if (!this.isCancelling) {
                        console.error(e);
                        cancelCb(e);
                    }
                }
            });

            res.on('end', () => {
                console.log('No more data in response.');
                if (!this.isCancelling) {
                    this.resetRequestState();
                }
            });

            res.on('error', (e) => {
                if (this.isCancelling) {
                    return;
                }
                console.error(e);
            });
        });
        this.currentRequest = req;

        req.on('error', (e) => {
            if (this.isCancelling) {
                return;
            }
            console.error(`Problem on request: ${e}`);
        });
        req.write(requestData);
        req.end();
        await finishePromise;
        this.resetRequestState();
    }

    public cancelCurrentQuery(): void {
        if (!this.currentRequest) {
            return;
        }
        this.isCancelling = true;
        this.currentRequest.destroy();
        this.finishActiveRequest?.();
    }
    
    public async stopActiveSession(): Promise<void> {
        this.cancelCurrentQuery();
        await this.sendStopSignal();
    }

    private resetRequestState(): void {
        this.currentRequest = undefined;
        this.finishActiveRequest = undefined;
        this.isCancelling = false;
    }

    private async sendStopSignal(): Promise<void> {
        if (!this.activeSessionId) {
            return;
        }
        const payload = Buffer.from(JSON.stringify({ session_id: this.activeSessionId }), 'utf-8');
        const options: RequestOptions = {
            hostname: 'localhost',
            port: this.connectToPort,
            path: '/session/stop',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': payload.length.toString()
            }
        };

        await new Promise<void>((resolve) => {
            const req = request(options, () => {
                resolve();
            });
            req.on('error', (err) => {
                console.error(`Failed to stop backend session: ${err}`);
                resolve();
            });
            req.write(payload);
            req.end();
        });
        this.activeSessionId = undefined;
    }
}
