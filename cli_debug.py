import subprocess
from pathlib import Path

cwd = Path(r'c:\SITE BOT DDISCORRD - Copie')
output = []
commands = [
    ['git', 'status', '--short'],
    ['git', 'log', '-1', '--oneline'],
    ['railway', 'status'],
    ['railway', 'service'],
    ['railway', 'up', '--service', 'shizu-bot-backend']
]
for cmd in commands:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
        output.append(f"COMMAND: {' '.join(cmd)}\nRETURNCODE: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n{'-'*80}\n")
    except Exception as e:
        output.append(f"COMMAND: {' '.join(cmd)}\nEXCEPTION: {e}\n{'-'*80}\n")
with open(cwd / 'cli_debug_output.txt', 'w', encoding='utf-8') as f:
    f.write(''.join(output))
print('done')
