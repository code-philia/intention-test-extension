# Intention Test VS Code Extension

## How to Run

> [!NOTE]
> Intention Test VS Code extension has not implemented one-click running for now.
> A local Python backend should be started before running the extension.

### Prerequisites

Intention Test requires the following development languages:

+ [**Python 3.10+**](https://www.python.org/downloads/) with [**PyTorch**](https://pytorch.org/get-started/locally/)
+ [**Node.js**](https://nodejs.org/en/download/package-manager)

And the following tools for source code analyzation:

+ [**Oracle JDK 1.8**](https://www.oracle.com/java/technologies/javase/javase8u211-later-archive-downloads.html) (with `JAVA_HOME` environment variable set to its path, and other JDK distributions are not tested)
+ [**Apache Maven**](https://maven.apache.org/download.cgi) (make sure `mvn`  or `mvn.cmd` could be found in the `PATH` environment variable)
+ [**CodeQL CLI**](https://docs.github.com/en/code-security/codeql-cli/getting-started-with-the-codeql-cli/setting-up-the-codeql-cli#1-download-the-codeql-cli-tar-archive)

And an [**OpenAI API key**](https://platform.openai.com/docs/guides/production-best-practices/api-keys) to access GPT-4o.

### Start up the Python backend

We suggest using **Python 3.10** which has been tested on.
First install the requirements:

```shell
cd backend

# For CPU / Apple Silicon
pip install -r requirements.txt

# For NVIDIA GPU (CUDA 12.4)
pip install -r requirements-cuda.txt
```

Modify the `backend/config.ini`:

```ini
[openai]
apikey = your-open-ai-key
url = https://api.openai.com/v1

[tools]
codeql = your-path-to-code-ql-executable
```

Then start the backend HTTP server:

```shell
# Start on default 8080 port
python server.py

# Start on another port
python server.py --port 12345
```

### Run the extension in debug mode

First install node dependencies from project root:

```shell
npm install
```

Then in VS Code, start the extension by the `Run Extension` debug option.

If you have specify another port when starting backend server,
change the port in **settings of the new Extension Development Host window** via `Intention Test: Port` before generating test cases.

### Use the demo project to try our tool

Now the tool only supports running on the demo project `backend/data/spark` inside this repository.

## Acknowledgements

+ Test tube icon comes from <https://www.svgrepo.com/svg/525096/test-tube-minimalistic>
