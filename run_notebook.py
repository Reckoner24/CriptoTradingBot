import json
import os

with open('notebooks/test 1.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

code_lines = []
for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        # Remove Plotly lines which require a frontend
        filtered_source = []
        for line in cell['source']:
            if not line.startswith('fig.show()'):
                filtered_source.append(line)
        code_lines.append("".join(filtered_source))

full_code = "\n".join(code_lines)

try:
    exec(full_code)
    print("Ejecución completada!")
except Exception as e:
    import traceback
    traceback.print_exc()
