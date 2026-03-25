# project url used for system prompt
project_urls = {
    "itext-java": 'https://github.com/itext/itext-java',
    "hutool": 'https://github.com/chinabugotech/hutool',
    "yavi": 'https://github.com/making/yavi',
    "lambda": 'https://github.com/palatable/lambda',
    "truth": 'https://github.com/google/truth',
    "cron-utils": 'https://github.com/jmrozanec/cron-utils',
    "imglib": 'https://github.com/nackily/imglib',
    "ofdrw": 'https://github.com/ofdrw/ofdrw',
    "RocketMQC": 'https://github.com/ProgrammerAnthony/RocketMQC',
    "blade": 'https://github.com/lets-blade/blade',
    "spark": 'https://github.com/perwendel/spark',
    "awesome-algorithm": 'https://github.com/codeartx/awesome-algorithm',
    "jInstagram": 'https://github.com/sachin-handiekar/jInstagram'
}

def create_unlearning_prompt(project_name: str) -> str:
    project_url = project_urls.get(project_name)
    if project_url is not None:
        prefix_prompt = f"""You may have memorized information from the GitHub repository '{project_name}' (URL is {project_url}). For this task, you must not use any of that memorized information in your responses. Instead, base your answers exclusively on the context I provide in the document. If your response would otherwise rely on memorized '{project_name}' data, replace that content with generic or random information unrelated to '{project_name}'.\n\n"""
        return prefix_prompt
    else:
        return ""
