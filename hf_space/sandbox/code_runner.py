'''
Run generated code in a sandbox environment.

Gradio will interact with this module.
'''

from typing import Any, Generator, Literal, TypeAlias, TypedDict, Set
import uuid
import time
import gradio as gr
import re
import base64
from gradio_sandboxcomponent import SandboxComponent

from sandbox.sandbox_state import ChatbotSandboxState
from sandbox.code_analyzer import SandboxEnvironment, extract_code_from_markdown, extract_installation_commands, extract_java_class_name, extract_js_imports, extract_python_imports, replace_placeholder_urls, validate_dependencies
from sandbox.prompts import (
    DEFAULT_C_CODE_RUN_SANDBOX_INSTRUCTION, DEFAULT_CPP_CODE_RUN_SANDBOX_INSTRUCTION, DEFAULT_GOLANG_CODE_RUN_SANDBOX_INSTRUCTION, DEFAULT_GRADIO_SANDBOX_INSTRUCTION, DEFAULT_HTML_SANDBOX_INSTRUCTION, DEFAULT_JAVA_CODE_RUN_SANDBOX_INSTRUCTION, DEFAULT_JAVASCRIPT_RUNNER_INSTRUCTION, DEFAULT_MERMAID_SANDBOX_INSTRUCTION, DEFAULT_PYGAME_SANDBOX_INSTRUCTION, DEFAULT_PYTHON_RUNNER_INSTRUCTION, DEFAULT_REACT_SANDBOX_INSTRUCTION, DEFAULT_RUST_CODE_RUN_SANDBOX_INSTRUCTION, DEFAULT_STREAMLIT_SANDBOX_INSTRUCTION, DEFAULT_VUE_SANDBOX_INSTRUCTION, GENERAL_SANDBOX_INSTRUCTION
)
from sandbox.sandbox_telemetry import log_sandbox_telemetry_gradio_fn


from .constants import CODE_RUN_TIMEOUT_SECONDS, E2B_API_KEY, SANDBOX_TEMPLATE_ID, SANDBOX_NGINX_PORT
from .sandbox_manager import get_sandbox_app_url, create_sandbox, install_npm_dependencies, install_pip_dependencies, reuse_or_create_sandbox, run_background_command_with_timeout, run_command_in_sandbox

SUPPORTED_SANDBOX_ENVIRONMENTS: list[str] = [
    env.value for env in SandboxEnvironment
    
]

WEB_UI_SANDBOX_ENVIRONMENTS = [
    SandboxEnvironment.HTML,
    SandboxEnvironment.REACT,
    SandboxEnvironment.VUE,
    SandboxEnvironment.GRADIO,
    SandboxEnvironment.STREAMLIT,
    # SandboxEnvironment.NICEGUI,
    SandboxEnvironment.PYGAME,
    SandboxEnvironment.MERMAID
]
'''
Sandbox environments that can be rendered in the web UI.
'''

VALID_GRADIO_CODE_LANGUAGES = [
    'python', 'c', 'cpp', 'markdown', 'json', 'html', 'css', 'javascript', 'jinja2', 'typescript', 'yaml', 'dockerfile', 'shell', 'r', 'sql',
    'sql-msSQL', 'sql-mySQL', 'sql-mariaDB', 'sql-sqlite', 'sql-cassandra', 'sql-plSQL', 'sql-hive', 'sql-pgSQL', 'sql-gql', 'sql-gpSQL', 'sql-sparkSQL',
    'sql-esper'
]
'''
Languages that gradio code component can render.
'''

RUN_CODE_BUTTON_HTML = "<button style='background-color: #4CAF50; border: none; color: white; padding: 10px 24px; text-align: center; text-decoration: none; display: inline-block; font-size: 16px; margin: 4px 2px; cursor: pointer; border-radius: 12px;'>Click to Run in Sandbox</button>"
'''
Button in the chat to run the code in the sandbox.
'''


DEFAULT_SANDBOX_INSTRUCTIONS: dict[SandboxEnvironment, str] = {
    SandboxEnvironment.AUTO: GENERAL_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.PYTHON_RUNNER: DEFAULT_PYTHON_RUNNER_INSTRUCTION.strip(),
    SandboxEnvironment.JAVASCRIPT_RUNNER: DEFAULT_JAVASCRIPT_RUNNER_INSTRUCTION.strip(),
    SandboxEnvironment.HTML: DEFAULT_HTML_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.REACT: DEFAULT_REACT_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.VUE: DEFAULT_VUE_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.GRADIO: DEFAULT_GRADIO_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.STREAMLIT: DEFAULT_STREAMLIT_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.PYGAME: DEFAULT_PYGAME_SANDBOX_INSTRUCTION.strip(),
    SandboxEnvironment.MERMAID: DEFAULT_MERMAID_SANDBOX_INSTRUCTION.strip(),
    # Runners
    SandboxEnvironment.C_RUNNER: DEFAULT_C_CODE_RUN_SANDBOX_INSTRUCTION,
    SandboxEnvironment.CPP_RUNNER: DEFAULT_CPP_CODE_RUN_SANDBOX_INSTRUCTION,
    SandboxEnvironment.JAVA_RUNNER: DEFAULT_JAVA_CODE_RUN_SANDBOX_INSTRUCTION,
    SandboxEnvironment.GOLANG_RUNNER: DEFAULT_GOLANG_CODE_RUN_SANDBOX_INSTRUCTION,
    SandboxEnvironment.RUST_RUNNER: DEFAULT_RUST_CODE_RUN_SANDBOX_INSTRUCTION,

}


SandboxGradioSandboxComponents: TypeAlias =  tuple[
    gr.Markdown | Any,  # sandbox_output_md
    SandboxComponent | Any,  # sandbox_ui
    gr.Code | Any,  # sandbox_code
    Any
]
'''
Gradio components for the sandbox.
'''

class CodeRunResult(TypedDict):
    '''
    The result of running the code in the sandbox.
    '''
    sandbox_id: str
    '''
    The sandbox id to run the code.
    '''
    sandbox_url: str
    '''
    The sandbox url to access the rendered results.
    '''
    is_run_success: bool
    '''
    Whether the code run is successful.
    '''
    stderr: str
    '''
    The stderr output from the sandbox.
    '''


def create_chatbot_sandbox_state(btn_list_length: int = 5) -> ChatbotSandboxState:
    '''
    Create a new sandbox state for a chatbot.
    '''
    return {
        'enable_sandbox': True,  # Always enabled
        'enabled_round': 0,
        'sandbox_run_round': 0,
        'edit_round': 0,
        'sandbox_environment': SandboxEnvironment.AUTO,
        'auto_selected_sandbox_environment': None,
        'sandbox_instruction': DEFAULT_SANDBOX_INSTRUCTIONS[SandboxEnvironment.AUTO],
        'code_to_execute': "",
        'code_language': None,
        'install_command': "",
        'btn_list_length': btn_list_length,
        'sandbox_id': None,
        'chat_session_id': None,
        'conv_id': None,
        "sandbox_output": None,
        "sandbox_error": None,
    }


def set_sandbox_state_ids(
    sandbox_state: ChatbotSandboxState,
    conv_id: str,
    chat_session_id: str,
) -> ChatbotSandboxState:
    '''
    Set the conv_id and chat_session_id in the sandbox state.
    '''
    sandbox_state['conv_id'] = conv_id
    sandbox_state['chat_session_id'] = chat_session_id
    return sandbox_state


def reset_sandbox_state(state: ChatbotSandboxState) -> ChatbotSandboxState:
    '''
    Reset the sandbox state.
    Used when the chatbot session is reset.
    '''
    # reset rounds
    state['enabled_round'] = 0
    state['sandbox_run_round'] = 0
    state['edit_round'] = 0

    # state['sandbox_environment'] = SandboxEnvironment.AUTO
    state['auto_selected_sandbox_environment'] = None
    state['sandbox_instruction'] = DEFAULT_SANDBOX_INSTRUCTIONS[SandboxEnvironment.AUTO]
    state['code_to_execute'] = ""
    state['code_language'] = None
    state['install_command'] = ""
    state['sandbox_error'] = None
    state['sandbox_output'] = None

    # reset ids
    state['sandbox_id'] = None
    state['conv_id'] = None
    state['chat_session_id'] = None

    return state


def update_sandbox_config_multi(
    enable_sandbox: bool,
    sandbox_environment: SandboxEnvironment,
    *states: ChatbotSandboxState
) -> list[ChatbotSandboxState]:
    '''
    Fn to update sandbox config.
    '''
    return [
        update_sandbox_config(enable_sandbox, sandbox_environment, state)
        for state
        in states
    ]


def update_sandbox_state_system_prompt(sandbox_state: ChatbotSandboxState, system_prompt: str):
    if sandbox_state['enabled_round'] == 0:
        sandbox_state['sandbox_instruction'] = system_prompt
    return sandbox_state


def update_sandbox_config(
    enable_sandbox: bool,
    sandbox_environment: SandboxEnvironment,
    state: ChatbotSandboxState
) -> ChatbotSandboxState:
    '''
    Fn to update sandbox config for single model.
    '''
    state["enable_sandbox"] = enable_sandbox
    state["sandbox_environment"] = sandbox_environment
    state['sandbox_instruction'] = DEFAULT_SANDBOX_INSTRUCTIONS.get(sandbox_environment, None)
    return state


def update_visibility(visible):
    return [gr.update(visible=visible)] *14


def update_visibility_for_single_model(visible: bool, component_cnt: int):
    return [gr.update(visible=visible)] * component_cnt


def mermaid_to_html(mermaid_code: str, theme: str = 'default') -> str:
    """
    Convert Mermaid diagram code to a minimal HTML document.

    Args:
        mermaid_code: The Mermaid diagram syntax
        theme: Theme name ('default', 'dark', 'forest', 'neutral', etc.)

    Returns:
        str: Complete HTML document with embedded Mermaid diagram
    """
    html_template = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: '{theme}',
            securityLevel: 'loose',
            fontFamily: 'Arial, sans-serif'
        }});
    </script>
</head>
<body>
    <div class="mermaid">
{mermaid_code}
    </div>
</body>
</html>'''
    return html_template


def javascript_to_html(javascript_code: str) -> str:
    """
    Convert JavaScript code to a minimal HTML document that executes the code.

    Args:
        javascript_code: The JavaScript code to embed

    Returns:
        str: Complete HTML document with embedded JavaScript code
    """
    html_template = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>JavaScript Code Execution</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        #output {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            margin-top: 20px;
            white-space: pre-wrap;
            font-family: monospace;
        }}
        .error {{
            color: red;
        }}
        .log {{
            color: black;
        }}
    </style>
</head>
<body>
    <h1>JavaScript Code Execution</h1>
    <div id="output"></div>
    
    <script>
        // Override console methods to capture output
        const outputDiv = document.getElementById('output');
        const originalConsole = {{}};
        
        ['log', 'error', 'warn', 'info'].forEach(function(method) {{
            originalConsole[method] = console[method];
            console[method] = function(...args) {{
                const message = args.map(function(arg) {{ 
                    return typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg);
                }}).join(' ');
                
                const span = document.createElement('span');
                span.className = method === 'error' ? 'error' : 'log';
                span.textContent = '[' + method.toUpperCase() + '] ' + message + '\\n';
                outputDiv.appendChild(span);
                
                // Also call original console method
                originalConsole[method].apply(console, args);
            }};
        }});
        
        // Capture uncaught errors
        window.addEventListener('error', function(e) {{
            const span = document.createElement('span');
            span.className = 'error';
            span.textContent = '[ERROR] ' + e.message + ' at line ' + e.lineno + '\\n';
            outputDiv.appendChild(span);
        }});
        
        try {{
            // Execute the user's JavaScript code
{javascript_code}
        }} catch (error) {{
            console.error('Execution error:', error.message);
        }}
    </script>
</body>
</html>'''
    return html_template


def render_result(result):
    if result.png:
        if isinstance(result.png, str):
            img_str = result.png
        else:
            img_str = base64.b64encode(result.png).decode()
        return f"![png image](data:image/png;base64,{img_str})"
    elif result.jpeg:
        if isinstance(result.jpeg, str):
            img_str = result.jpeg
        else:
            img_str = base64.b64encode(result.jpeg).decode()
        return f"![jpeg image](data:image/jpeg;base64,{img_str})"
    elif result.svg:
        if isinstance(result.svg, str):
            svg_data = result.svg
        else:
            svg_data = result.svg.decode()
        svg_base64 = base64.b64encode(svg_data.encode()).decode()
        return f"![svg image](data:image/svg+xml;base64,{svg_base64})"
    elif result.html:
        return result.html
    elif result.markdown:
        return f"```markdown\n{result.markdown}\n```"
    elif result.latex:
        return f"```latex\n{result.latex}\n```"
    elif result.json:
        return f"```json\n{result.json}\n```"
    elif result.javascript:
        return result.javascript  # Return raw JavaScript
    else:
        return str(result)


def run_code_interpreter(code: str, code_language: str | None, install_command: str) -> tuple[str, str]:
    """
    Executes the provided code within a sandboxed environment and returns the output.

    Args:
        code (str): The code to be executed.
    """
    sandbox = create_sandbox(is_code_sandbox=True)

    stderrs = []

    # Run install command if provided
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")

    # Add virtual environment to Python path and run user code
    execution = sandbox.run_code(
        code=f"""
import sys, glob
for path in glob.glob("/home/user/.venv/lib/python*/site-packages"):
    if path not in sys.path: sys.path.insert(0, path)

{code}""",
        language=code_language
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(execution.logs.stdout)
    stderr = "\n".join(execution.logs.stderr)
    if execution.error:
        stderr += f"\n{execution.error.name}: {execution.error.value}"
    output = ""
    if stdout:
        output += f"```markdown\n{stdout}\n```\n\n"

    stderrs.append(stderr)

    results = []
    for result in execution.results:
        if result.html or result.javascript:
            # TODO: fix this
            continue
            # with open('html_code.html', 'w') as f:
            #     f.write(result.html)
            # url, _ = run_html_sandbox(result.html, ([], extract_js_imports(result.html)))
        else:
            rendered_result = render_result(result)
            results.append(rendered_result)
    if results:
        output += "\n### Results:\n" + "\n".join(results)

    stderrs = '\n'.join(stderrs)
    return output, "" if output else stderrs


def run_html_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> tuple[str, str, str]:
    """
    Executes the provided code within a sandboxed environment and returns the output.
    Supports both React and Vue.js rendering in HTML files.

    Args:
        code (str): The code to be executed.
        install_command (str): Bash command to install dependencies

    Returns:
        tuple: (sandbox_url, sandbox_id, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)
    project_root = "~/html_app"
    sandbox.files.make_dir(project_root)

    # Run install command if provided
    stderrs = []
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with HTML setup
            stderrs.append(f"Install command failed: {' '.join(stderr)}")

    # replace placeholder URLs with SVG data URLs
    code = replace_placeholder_urls(code)

    file_path = f"{project_root}/index.html"
    sandbox.files.write(file_path, code, "user", 60)

    sandbox_url = get_sandbox_app_url(sandbox, 'html')
    return (sandbox_url, sandbox.sandbox_id, '\n'.join(stderrs))


def run_react_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> CodeRunResult:
    """
    Executes the provided code within a sandboxed environment and returns the output.

    Args:
        code (str): The code to be executed.
        install_command (str): Bash command to install dependencies

    Returns:
        url for remote sandbox
    """
    project_root = "~/react_app"
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    stderrs: list[str] = [] # to collect errors

    # replace placeholder URLs with SVG data URLs
    code = replace_placeholder_urls(code)

    # set up the sandbox directory structure first
    print("Setting up sandbox directory structure...")
    file_path = "~/react_app/src/App.tsx"
    sandbox.files.write(file_path, code, "user", 60)
    print("Code files written successfully.")

    # Run install command AFTER setting up the project structure
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
            working_directory=project_root,  # Run in the correct directory
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with build attempt
            stderrs.append(f"Install command failed: {' '.join(stderr)}")

    # Attempt to build the React app
    is_run_success, _, build_stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command="npm run build --loglevel=error -- --mode development --logLevel error",
        working_directory=project_root,
    )
    stderrs.extend(build_stderrs)

    # Always try to get the sandbox URL, even if build failed
    sandbox_url = get_sandbox_app_url(sandbox, 'react')
    
    # If build failed but we have a sandbox, still return the URL
    if not is_run_success and sandbox_url:
        is_run_success = True  # Consider it successful if we have a working sandbox
    
    return {
        'sandbox_id': sandbox.sandbox_id,
        'sandbox_url': sandbox_url,
        'is_run_success': is_run_success,
        'stderr': '\n'.join(stderrs),
    }


def run_vue_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> CodeRunResult:
    """
    Executes the provided Vue code within a sandboxed environment and returns the output.

    Args:
        code (str): The Vue code to be executed.
        install_command (str): Bash command to install dependencies

    Returns:
        url for remote sandbox
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)
    project_root = "~/vue_app"

    stderrs: list[str] = [] # to collect errors

    # replace placeholder URLs with SVG data URLs
    code = replace_placeholder_urls(code)

    # Set up the sandbox directory structure first
    file_path = "~/vue_app/src/App.vue"
    sandbox.files.write(file_path, code, "user", 60)

    # Run install command AFTER setting up the project structure
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
            working_directory=project_root,  # Run in the correct directory
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with build attempt
            stderrs.append(f"Install command failed: {' '.join(stderr)}")

    # Attempt to build the Vue app
    is_run_success, _, build_stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command="npm run build --loglevel=error -- --mode development --logLevel error",
        working_directory=project_root,
    )
    stderrs.extend(build_stderrs)

    # Always try to get the sandbox URL, even if build failed
    sandbox_url = get_sandbox_app_url(sandbox, 'vue')
    
    # If build failed but we have a sandbox, still return the URL
    if not is_run_success and sandbox_url:
        print(f"⚠️ Build failed but sandbox is available at: {sandbox_url}")
        is_run_success = True  # Consider it successful if we have a working sandbox
    
    return {
        'sandbox_id': sandbox.sandbox_id,
        'sandbox_url': sandbox_url,
        'is_run_success': is_run_success,
        'stderr': '\n'.join(stderrs),
    }


def run_pygame_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> CodeRunResult:
    """
    Executes the provided code within a sandboxed environment and returns the output.

    Args:
        code (str): The code to be executed.
        install_command (str): Bash command to install dependencies

    Returns:
        url for remote sandbox
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)
    project_root = "~/pygame_app"
    file_path = f"{project_root}/main.py"

    stderrs = []

    # Set up the sandbox directory structure first
    sandbox.files.write(file_path, code, "user", 60)

    # Run install command AFTER setting up the project structure
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
            working_directory=project_root,  # Run in the correct directory
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with build attempt
            stderrs.append(f"Install command failed: {' '.join(stderr)}")

    # Attempt to build the pygame code
    is_run_success, _, build_stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command="pygbag --build ~/pygame_app",
    )
    stderrs.extend(build_stderrs)

    # Always try to get the sandbox URL, even if build failed
    sandbox_url = get_sandbox_app_url(sandbox, 'pygame')
    
    # If build failed but we have a sandbox, still return the URL
    if not is_run_success and sandbox_url:
        print(f"⚠️ Build failed but sandbox is available at: {sandbox_url}")
        is_run_success = True  # Consider it successful if we have a working sandbox
    
    return {
        'sandbox_id': sandbox.sandbox_id,
        'sandbox_url': sandbox_url,
        'is_run_success': is_run_success,
        'stderr': '\n'.join(stderrs),
    }


def run_gradio_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> tuple[str, str, str]:
    """
    Executes the provided code within a sandboxed environment and returns the output.

    Args:
        code (str): The code to be executed.
        install_command (str): Bash command to install dependencies

    Returns:
        url for remote sandbox and sandbox id
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    file_path = "~/gradio_app/main.py"

    # Remove server_port and server_name arguments from demo.launch() calls
    code = re.sub(r'\.launch\([^)]*server_port\s*=\s*[^,)]+[,\s]*', '.launch(', code)
    code = re.sub(r'\.launch\([^)]*server_name\s*=\s*[^,)]+[,\s]*', '.launch(', code)
    
    # Ensure demo.launch() uses the correct server configuration
    if 'demo.launch(' in code:
        # Replace demo.launch() with proper configuration
        code = re.sub(
            r'demo\.launch\([^)]*\)',
            f'demo.launch(server_name="0.0.0.0", server_port=7860, share=False)',
            code
        )
    elif '.launch(' in code:
        # Handle other patterns like app.launch(), interface.launch(), etc.
        code = re.sub(
            r'(\w+)\.launch\([^)]*\)',
            rf'\1.launch(server_name="0.0.0.0", server_port=7860, share=False)',
            code
        )
    else:
        # If no launch() call found, add one at the end
        code += f'\n\n# Auto-added launch configuration\nif __name__ == "__main__":\n    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)'

    sandbox.files.write(file_path, code, "user", 60)

    stderrs = []

    # Run install command if provided
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with Gradio setup
            stderrs.append(f"Install command failed: {' '.join(stderr)}")
    stderr = run_background_command_with_timeout(
        sandbox,
        f"python {file_path}",
        timeout=15,
    )
    stderrs.append(stderr)

    sandbox_url = 'https://' + sandbox.get_host(7860)

    return (sandbox_url, sandbox.sandbox_id, '\n'.join(stderrs))


def run_streamlit_sandbox(code: str, install_command: str, existing_sandbox_id: str | None = None) -> tuple[str, str, str]:
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    stderrs = []

    sandbox.files.make_dir('mystreamlit')
    file_path = "~/mystreamlit/app.py"
    sandbox.files.write(file_path, code, "user", 60)

    # Run install command if provided
    if install_command.strip():
        is_success, stdout, stderr = run_command_in_sandbox(
            sandbox=sandbox,
            command=install_command,
            timeout=60 * 3,
        )
        if stderr:
            stderrs.extend(stderr)
        if not is_success:
            print(f"Install command failed: {stderr}")
            # Don't return early - continue with Streamlit setup
            stderrs.append(f"Install command failed: {' '.join(stderr)}")

    stderr = run_background_command_with_timeout(
        sandbox,
        r"sudo kill -9 $(ss -lptn 'sport = :8501' | grep -oP '(?<=pid=)\d+'); streamlit run ~/mystreamlit/app.py --server.port 8501 --server.headless true",
        timeout=15,
    )
    stderrs.append(stderr)

    host = sandbox.get_host(port=8501)
    url = f"https://{host}"
    return (url, sandbox.sandbox_id, '\n'.join(stderrs))


def run_c_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
    """
    Executes the provided C code within a sandboxed environment and returns the output.

    Args:
        code (str): The C code to be executed.

    Returns:
        tuple: (stdout, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    file_path = "~/main.c"
    sandbox.files.write(file_path, code, "user", 60)

    is_success, stdouts, stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command=f"gcc {file_path} -o ~/main && ./main",
        timeout=CODE_RUN_TIMEOUT_SECONDS,
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(stdouts)
    stderr = "\n".join(stderrs)
    return stdout, stderr


def run_cpp_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
    """
    Executes the provided C++ code within a sandboxed environment and returns the output.

    Args:
        code (str): The C++ code to be executed.

    Returns:
        tuple: (stdout, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    file_path = "~/main.cpp"
    sandbox.files.write(file_path, code, "user", 60)

    is_success, stdouts, stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command=f"g++ {file_path} -o ~/main && ./main",
        timeout=CODE_RUN_TIMEOUT_SECONDS,
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(stdouts)
    stderr = "\n".join(stderrs)
    return stdout, stderr


def run_java_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
    """
    Executes the provided Java code within a sandboxed environment and returns the output.

    Args:
        code (str): The Java code to be executed.

    Returns:
        tuple: (stdout, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    class_name = extract_java_class_name(code)
    file_path = f"~/{class_name}.java"
    sandbox.files.write(file_path, code, "user", 60)

    is_success, stdouts, stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command=f"javac {file_path} && java {class_name}",
        timeout=CODE_RUN_TIMEOUT_SECONDS,
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(stdouts)
    stderr = "\n".join(stderrs)
    return stdout, stderr


def run_golang_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
    """
    Executes the provided Go code within a sandboxed environment and returns the output.

    Args:
        code (str): The Go code to be executed

    Returns:
        tuple: (stdout, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    file_path = "~/main.go"
    sandbox.files.write(file_path, code, "user", 60)

    is_success, stdouts, stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command=f"go run {file_path}",
        timeout=CODE_RUN_TIMEOUT_SECONDS,
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(stdouts)
    stderr = "\n".join(stderrs)
    return stdout, stderr


# def run_csharp_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
#     """
#     Executes the provided C# code within a sandboxed environment and returns the output.

#     Args:
#         code (str): The C# code to be executed

#     Returns:
#         tuple: (stdout, stderr)
#     """
#     sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

#     file_path = "~/main.cs"
#     sandbox.files.write(file_path, code, "user", 60)

#     is_success, stdouts, stderrs = run_command_in_sandbox(
#         sandbox=sandbox,
#         command=f"mcs {file_path} && mono main.exe",
#         timeout=CODE_RUN_TIMEOUT_SECONDS,
#     )

#     # collect stdout, stderr from sandbox
#     stdout = "\n".join(stdouts)
#     stderr = "\n".join(stderrs)
#     return stdout, stderr


def run_rust_code(code: str, existing_sandbox_id: str | None = None) -> tuple[str, str]:
    """
    Executes the provided Rust code within a sandboxed environment and returns the output.

    Args:
        code (str): The Rust code to be executed

    Returns:
        tuple: (stdout, stderr)
    """
    sandbox = reuse_or_create_sandbox(sandbox_id=existing_sandbox_id)

    file_path = "~/main.rs"
    sandbox.files.write(file_path, code, "user", 60)

    is_success, stdouts, stderrs = run_command_in_sandbox(
        sandbox=sandbox,
        command=f"rustc {file_path} && ./main",
        timeout=CODE_RUN_TIMEOUT_SECONDS,
    )

    # collect stdout, stderr from sandbox
    stdout = "\n".join(stdouts)
    stderr = "\n".join(stderrs)
    return stdout, stderr


def on_edit_code(
    state,
    sandbox_state: ChatbotSandboxState,
    sandbox_output_md: gr.Markdown,
    sandbox_ui: SandboxComponent,
    sandbox_code: str,
    sandbox_dependency: gr.Dataframe,
) -> Generator[tuple[Any, Any, Any, Any], None, None]:
    '''
    Gradio Handler when code is edited manually by users.
    '''
    if sandbox_state['enable_sandbox'] is False:
        yield None, None, None, None
        return
    if len(sandbox_code.strip()) == 0 or sandbox_code == sandbox_state['code_to_execute']:
        yield gr.skip(), gr.skip(), gr.skip(), gr.skip()
        return
    sandbox_state['code_to_execute'] = sandbox_code

    # Create empty dependencies dataframe for UI compatibility
    dependencies = [["python", "", ""], ["npm", "", ""]]

    # Keep existing install command
    # No need to update install_command here as it's set from the original message

    yield (
        gr.skip(),  # sandbox_output_md
        gr.skip(),  # sandbox_ui
        gr.skip(),  # sandbox_code
        gr.update(value=dependencies),  # sandbox_dependency
    )
    yield from on_run_code(
        state,
        sandbox_state,
        sandbox_output_md,
        sandbox_ui,
        sandbox_code,
        sandbox_dependency,
    )


def on_edit_dependency(
    state,
    sandbox_state: ChatbotSandboxState,
    sandbox_dependency: gr.Dataframe,
    sandbox_output_md: gr.Markdown,
    sandbox_ui: SandboxComponent,
    sandbox_code: str,
) -> Generator[tuple[Any, Any, Any, Any], None, None]:
    """
    Gradio Handler when dependencies are edited manually by users.
    Handles version specifications and dependency removal.
    """
    if sandbox_state["enable_sandbox"] is False:
        yield None, None, None, None
        return

    # Validate dependencies format
    is_valid, error_msg = validate_dependencies(sandbox_dependency)
    if not is_valid:
        yield (
            gr.Markdown(f"Invalid dependencies: {error_msg}"),
            gr.skip(),
            gr.skip(),
            sandbox_dependency,  # Return original dataframe
        )
        return

    # Convert dataframe format to separate python and npm lists
    python_deps = []
    npm_deps = []
    for dep in sandbox_dependency:
        dep_type, pkg_name, version = dep
        pkg_name = pkg_name.strip()
        version = version.strip()

        # Skip empty rows
        if not pkg_name:
            continue

        if dep_type.lower() == "python":
            # Handle Python package with version
            if version and version.lower() != "latest":
                if not any(op in version for op in ["==", ">=", "<=", "~=", ">", "<"]):
                    python_deps.append(f"{pkg_name}=={version}")
                else:
                    python_deps.append(f"{pkg_name}{version}")
            else:
                python_deps.append(pkg_name)

        elif dep_type.lower() == "npm":
            # Handle NPM package with version
            if version and version.lower() != "latest":
                if not version.startswith("@"):
                    version = "@" + version
                npm_deps.append(f"{pkg_name}{version}")
            else:
                npm_deps.append(pkg_name)

    # Update sandbox state with new install command
    # For now, we'll keep the existing install_command as dependency editing is simplified
    # In a full implementation, you might want to convert the dependency edits to install commands

    # increase edit round
    sandbox_state['edit_round'] += 1

    # First yield: Update UI with success message
    yield (
        gr.Markdown("Dependencies updated successfully"),
        gr.skip(),  # sandbox_ui
        gr.skip(),  # sandbox_code
        sandbox_dependency,  # Return the same dataframe
    )

    # Second yield: Run code with new dependencies
    yield from on_run_code(
        state,
        sandbox_state,
        sandbox_output_md,
        sandbox_ui,
        sandbox_code,
        sandbox_dependency,
    )


def on_click_code_message_run(
    state,
    sandbox_state: ChatbotSandboxState,
    sandbox_output_md: gr.Markdown,
    sandbox_ui: SandboxComponent,
    sandbox_code: str,
    sandbox_dependency: gr.Dataframe,
    evt: gr.SelectData
) -> Generator[SandboxGradioSandboxComponents, None, None]:
    '''
    Gradio Handler when run code button in message is clicked. Update Sandbox components.
    '''
    print("on_click_code_message_run")

    if sandbox_state['enable_sandbox'] is False:
        yield None, None, None, None
        return
    if not evt.value.endswith(RUN_CODE_BUTTON_HTML):
        yield gr.skip(), gr.skip(), gr.skip(), gr.skip()
        return

    message = evt.value.replace(RUN_CODE_BUTTON_HTML, "").strip()
    extract_result = extract_code_from_markdown(
        message=message,
        enable_auto_env=sandbox_state['sandbox_environment'] == SandboxEnvironment.AUTO
    )
    if extract_result is None:
        yield gr.skip(), gr.skip(), gr.skip(), gr.skip()
        return

    code, code_language, env_selection, install_command = extract_result

    # As sandbox is reused, no need to skip
    # if sandbox_state['code_to_execute'] == code and sandbox_state['code_language'] == code_language:
    #     # skip if no changes
    #     yield gr.skip(), gr.skip(), gr.skip(), gr.skip()
    #     return

    if code_language == 'tsx':
        code_language = 'typescript'
    code_language = code_language.lower()
    gradio_code_language = code_language.lower() if code_language and code_language.lower(
        # ensure gradio supports the code language
    ) in VALID_GRADIO_CODE_LANGUAGES else None

    # Create empty dependencies dataframe for UI compatibility
    dependencies = [["python", "", ""], ["npm", "", ""]]

    sandbox_state['code_to_execute'] = code
    sandbox_state['code_language'] = code_language
    sandbox_state['install_command'] = install_command
    if sandbox_state['sandbox_environment'] == SandboxEnvironment.AUTO:
        sandbox_state['auto_selected_sandbox_environment'] = env_selection

    # reset edit round
    sandbox_state['edit_round'] = 0

    yield (
        gr.skip(),  # sandbox_output_md
        gr.skip(),  # sandbox_ui
        gr.update(value=code, language=gradio_code_language),  # sandbox_code
        gr.update(value=dependencies)  # sandbox_dependency
    )

    yield from on_run_code(
        state,
        sandbox_state,
        sandbox_output_md,
        sandbox_ui,
        sandbox_code,
        sandbox_dependency,
    )


def on_run_code(
    state,
    sandbox_state: ChatbotSandboxState,
    sandbox_output_md: gr.Markdown,
    sandbox_ui: SandboxComponent,
    sandbox_code: str,
    sandbox_dependency: gr.Dataframe,
) -> Generator[tuple[Any, Any, Any, Any], None, None]:
    '''
    gradio fn when run code button is clicked. Update Sandbox components.
    '''
    print("on_run_code")

    if sandbox_state['enable_sandbox'] is False:
        yield None, None, None, None
        return

    # validate e2b api key
    if not E2B_API_KEY:
        raise ValueError("E2B_API_KEY is not set in env vars.")

    # hide and change value of the current sandbox UI to force refresh the sandbox
    # otherwise the sandbox might not change if the url is same
    yield (
        gr.skip(),
        SandboxComponent(
            value=('', False, []),
            label="Example",
            visible=False,
        ),
        gr.skip(),
        gr.skip(),
    )

    code, code_language = sandbox_state['code_to_execute'], sandbox_state['code_language']
    if code is None or code_language is None:
        yield None, None, None, None
        return

    gradio_code_language = code_language.lower() if code_language and code_language.lower(
        # ensure gradio supports the code language
    ) in VALID_GRADIO_CODE_LANGUAGES else None

    # Get install command from sandbox state
    install_command = sandbox_state.get('install_command', '')
    
    # Create empty dependencies dataframe for UI compatibility
    dependencies = [["python", "", ""], ["npm", "", ""]]

    # Initialize output with loading message
    markdown_output_text = "### Sandbox Execution Log\n\n"
    yield (
        gr.Markdown(
            value=markdown_output_text + "🔄 Initializing sandbox environment...", visible=True
        ),
        SandboxComponent(visible=False),
        gr.Code(value=code, language=gradio_code_language, visible=True),
        gr.update(value=dependencies, visible=True),  # Update with unified dependencies
    )

    # Use auto_selected_sandbox_environment only when in AUTO mode, otherwise use sandbox_environment
    sandbox_env = (
        sandbox_state['auto_selected_sandbox_environment'] 
        if sandbox_state['sandbox_environment'] == SandboxEnvironment.AUTO
        else sandbox_state['sandbox_environment']
    )

    def update_markdown_output(message: str, clear_output: bool = False):
        nonlocal markdown_output_text
        if clear_output:
            markdown_output_text = ""
        markdown_output_text += f"\n{message}"
        return (
            gr.Markdown(value=markdown_output_text, visible=True, sanitize_html=False),
            gr.skip(),
            gr.skip(),
            gr.skip()  # Always include dependencies update
        )

    sandbox_id: str | None = sandbox_state["sandbox_id"]  # the sandbox id
    sandbox_output: str = "" # stdout from sandbox
    sandbox_error: str = ""  # stderr from sandbox
    print(f"sandbox_env: {sandbox_env}")
    match sandbox_env:
        case SandboxEnvironment.HTML:
            yield update_markdown_output("🔄 Setting up HTML sandbox...")
            sandbox_url, sandbox_id, sandbox_error = run_html_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            if sandbox_error:
                yield update_markdown_output("❌ HTML sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ HTML sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(sandbox_url, True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.REACT:
            yield update_markdown_output("🔄 Setting up React sandbox...")
            code_run_result = run_react_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            sandbox_id, sandbox_error = code_run_result['sandbox_id'], code_run_result['stderr']
            if code_run_result['is_run_success'] is False and sandbox_error:
                yield update_markdown_output("❌ React sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ React sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(code_run_result['sandbox_url'], True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.VUE:
            yield update_markdown_output("🔄 Setting up Vue sandbox...")
            code_run_result = run_vue_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            sandbox_id, sandbox_error = code_run_result['sandbox_id'], code_run_result['stderr']
            if code_run_result['is_run_success'] is False and code_run_result['stderr']:
                yield update_markdown_output("❌ Vue sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{code_run_result['stderr']}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Vue sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(code_run_result['sandbox_url'], True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.PYGAME:
            yield update_markdown_output("🔄 Setting up PyGame sandbox...")
            code_run_result = run_pygame_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            sandbox_id, sandbox_error = code_run_result['sandbox_id'], code_run_result['stderr']
            if code_run_result['is_run_success'] is False and code_run_result['stderr']:
                yield update_markdown_output("❌ PyGame sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{code_run_result['stderr']}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ PyGame sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(code_run_result['sandbox_url'], True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.GRADIO:
            yield update_markdown_output("🔄 Setting up Gradio sandbox...")
            sandbox_url, sandbox_id, sandbox_error = run_gradio_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            if sandbox_error:
                yield update_markdown_output("❌ Gradio sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Gradio sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(sandbox_url, True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.STREAMLIT:
            yield update_markdown_output("🔄 Setting up Streamlit sandbox...")
            sandbox_url, sandbox_id, sandbox_error = run_streamlit_sandbox(
                code=code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            if sandbox_error:
                yield update_markdown_output("❌ Streamlit sandbox failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Streamlit sandbox is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(sandbox_url, True, []),
                        label="Example",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.MERMAID:
            yield update_markdown_output("🔄 Setting up Mermaid visualization...")
            # Convert Mermaid to HTML at execution time
            html_code = mermaid_to_html(code, theme='light')
            sandbox_url, sandbox_id, sandbox_error = run_html_sandbox(
                code=html_code,
                install_command=install_command,
                existing_sandbox_id=sandbox_state['sandbox_id'],
            )
            if sandbox_error:
                yield update_markdown_output("❌ Mermaid visualization failed to render!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Mermaid visualization is ready!", clear_output=True)
                yield (
                    gr.Markdown(value=markdown_output_text, visible=True),
                    SandboxComponent(
                        value=(sandbox_url, True, []),
                        label="Mermaid Diagram",
                        visible=True,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.PYTHON_RUNNER:
            yield update_markdown_output("🔄 Running Python Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_code_interpreter(
                code=code, code_language='python', install_command=install_command
            )
            if sandbox_error:
                yield update_markdown_output("❌ Python Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + sandbox_output,
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.JAVASCRIPT_RUNNER:
            yield update_markdown_output("🔄 Running JavaScript Runner...", clear_output=True)
            # Convert JavaScript code to HTML
            html_code = javascript_to_html(code)
            # Run the HTML in sandbox
            sandbox_url, sandbox_id, sandbox_error = run_html_sandbox(
                code=html_code, install_command=install_command, sandbox_id=sandbox_state.get('sandbox_id')
            )
            # Update sandbox state with the sandbox_id
            sandbox_state['sandbox_id'] = sandbox_id
            if sandbox_error:
                yield update_markdown_output("❌ JavaScript Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text,
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=(sandbox_url, True, []),
                        label="JavaScript Sandbox",
                        visible=True,
                        key=f"js_sandbox_{int(time.time() * 1000)}",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.C_RUNNER:
            yield update_markdown_output("🔄 Running C Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_c_code(
                code=code, existing_sandbox_id=sandbox_state['sandbox_id']
            )
            if sandbox_error:
                yield update_markdown_output("❌ C Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + f"```markdown\n{sandbox_output}\n```",
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.CPP_RUNNER:
            yield update_markdown_output("🔄 Running C++ Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_cpp_code(
                 code=code, existing_sandbox_id=sandbox_state['sandbox_id']
            )
            if sandbox_error:
                yield update_markdown_output("❌ C++ Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + f"```markdown\n{sandbox_output}\n```",
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.JAVA_RUNNER:
            yield update_markdown_output("🔄 Running Java Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_java_code(
                 code=code, existing_sandbox_id=sandbox_state['sandbox_id']
            )
            if sandbox_error:
                yield update_markdown_output("❌ Java Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + f"```markdown\n{sandbox_output}\n```",
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case SandboxEnvironment.GOLANG_RUNNER:
            yield update_markdown_output("🔄 Running Go Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_golang_code(
                code=code, existing_sandbox_id=sandbox_state['sandbox_id']
            )
            if sandbox_error:
                yield update_markdown_output("❌ Go Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + f"```markdown\n{sandbox_output}\n```",
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        # case SandboxEnvironment.CSHARP_RUNNER:
        #     yield update_markdown_output("🔄 Running C# Runner...", clear_output=True)
        #     output, stderr = run_csharp_code(
        #         code=code, existing_sandbox_id=sandbox_state['sandbox_id']
        #     )
        #     yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
        #     if output:
        #         yield update_markdown_output(f"### Stdout:\n```markdown\n{output}\n```\n\n")
        #     if stderr:
        #         yield update_markdown_output(f"### Stderr:\n```markdown\n{stderr}\n```\n\n")
        case SandboxEnvironment.RUST_RUNNER:
            yield update_markdown_output("🔄 Running Rust Runner...", clear_output=True)
            sandbox_output, sandbox_error = run_rust_code(
                code=code, existing_sandbox_id=sandbox_state['sandbox_id']
            )
            if sandbox_error:
                yield update_markdown_output("❌ Rust Runner failed to run!", clear_output=True)
                yield update_markdown_output(f"<details open><summary><strong>🚨 Stderr</strong></summary>\n\n```\n{sandbox_error}\n```\n\n</details>\n\n")
            else:
                yield update_markdown_output("✅ Code execution is ready!", clear_output=True)
                yield (
                    gr.Markdown(
                        value=markdown_output_text + "\n\n" + f"```markdown\n{sandbox_output}\n```",
                        sanitize_html=False,
                        visible=True,
                    ),
                    SandboxComponent(
                        value=("", False, []),
                        label="Example",
                        visible=False,
                        key="newsandbox",
                    ),
                    gr.skip(),
                    gr.skip(),
                )
        case _:
            yield (
                gr.Markdown(value=code, visible=True),
                SandboxComponent(
                    value=("", False, []),
                    label="Example",
                    visible=False,
                    key="newsandbox",
                ),
                gr.skip(),
                gr.skip(),
            )

    sandbox_state['sandbox_run_round'] += 1
    sandbox_state["sandbox_output"] = sandbox_output  # record sandbox output if exists
    sandbox_state["sandbox_error"] = sandbox_error  # record sandbox error if exists
    # generate a random sandbox id if not exists as some code runners might not return sandbox id
    sandbox_state['sandbox_id'] = sandbox_id if sandbox_id else str(uuid.uuid4())
    log_sandbox_telemetry_gradio_fn(
        sandbox_state=sandbox_state,
        sandbox_ui_value=None,
    )

    print("on_run_code done")