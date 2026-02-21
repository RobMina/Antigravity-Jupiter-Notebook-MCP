# antigravity-nb

A Jupyter notebook MCP server for [Antigravity](https://antigravity.codes) — lets AI agents read, edit, and execute `.ipynb` notebooks directly inside your workspace.

## What it does

- Exposes **10 tools** over the [Model Context Protocol](https://modelcontextprotocol.io) (stdio transport)
- Antigravity agents can open notebooks, read/edit/insert/delete cells, run them cell-by-cell or as tagged pipeline stages, and restart the kernel
- Paths are sandboxed to your workspace root — only `.ipynb` files are allowed

## Install

### From GitHub (recommended)

```bash
pip install git+https://github.com/Ian747-tw/Antigravity-Jupiter-Notebook-MCP.git
```

### For local development

```bash
git clone https://github.com/Ian747-tw/Antigravity-Jupiter-Notebook-MCP.git
cd antigravity-nb
pip install -e .
```

## Add to Antigravity

### 1. Locate your configuration file

Open your Antigravity configuration file. It is usually found at:

```
~/.gemini/antigravity/mcp_config.json
```

Or go to **Settings → MCP Servers** inside Antigravity.

### 2. Add the server

Append the following to your `mcpServers` object:

```json
{
  "mcpServers": {
    "antigravity-nb": {
      "command": "antigravity-nb",
      "args": ["serve-agent", "--workspace-root", "${workspaceFolder}"]
    }
  }
}
```

### 3. Reload

Restart Antigravity or trigger **Refresh MCP Servers** to discover the new tools.

### Verify

Ask the agent:

> "List the tools available from antigravity-nb"
> "Open a notebook and run the first cell"

Once connected, Antigravity discovers all 10 tools automatically. You can then ask it things like:

> "Run the preprocess stage in pipeline.ipynb and show me the outputs"
> "Edit cell 2 in analysis.ipynb to use pandas instead of a plain list"
> "Run all cells in notebook.ipynb and tell me if any failed"

## Troubleshooting

### Kernel not found / ModuleNotFoundError

If you see `ModuleNotFoundError` when running a cell, the notebook is executing in a kernel that doesn't have your packages installed. Check available kernels and install one that matches your environment:

```bash
# List installed kernels
jupyter kernelspec list

# Install the current environment as a kernel
python -m ipykernel install --user --name myenv
```

Then pass `kernel_name` when calling `run_cell` or `run_range`, or restart Antigravity and select the correct kernel.

### Pipeline tags

To use the `run_pipeline` tool, tag your cells in the notebook metadata. In JupyterLab: **View → Cell Toolbar → Tags**, then add a tag like `preprocess`, `train`, or `eval` to each cell.

The agent can then run specific stages in order while maintaining kernel state across them:

> "Run the train and eval stages in model.ipynb"

### Debug logging

Run the server manually and pipe stderr to a file to see all tool calls and errors:

```bash
antigravity-nb serve-agent --workspace-root . 2>debug.log
tail -f debug.log
```

## Available tools

| Tool | Description |
|---|---|
| `open_notebook` | Open a notebook and return cell count + pipeline stages |
| `list_cells` | List all cells with index, type, tags, and source preview |
| `read_cell` | Read the full source and outputs of one cell |
| `edit_cell` | Replace a cell's source (auto-checkpoints before editing) |
| `insert_cell` | Insert a new cell at a given index |
| `delete_cell` | Delete a cell (auto-checkpoints before deleting) |
| `run_cell` | Execute one code cell and return outputs |
| `run_range` | Execute a range of cells `[start, end]` inclusive |
| `run_pipeline` | Execute cells grouped by tag-based pipeline stages |
| `restart_kernel` | Restart the Jupyter kernel, clearing all in-memory state |

## Checkpoints

`edit_cell` and `delete_cell` write a timestamped backup before making changes:

```
notebook.checkpoint_20250610_143022.ipynb
```

Pass `checkpoint=false` to skip if you don't need it.

## CLI

The CLI is also available for scripting:

```bash
# Run a single cell
antigravity-nb run-cell notebook.ipynb 3

# Run a range of cells
antigravity-nb run-range notebook.ipynb 2 7

# Run a tagged pipeline
antigravity-nb run-pipeline notebook.ipynb
antigravity-nb run-pipeline notebook.ipynb --stage preprocess --stage train

# Edit a cell from a file
antigravity-nb edit-cell notebook.ipynb 5 --source-file ./new_cell.py

# List pipeline stages
antigravity-nb list-stages notebook.ipynb

# Start the MCP server manually
antigravity-nb serve-agent --workspace-root .
```

## Python API

```python
from antigravity_nb import NotebookAdapter, KernelSession, NotebookRunner

nb = NotebookAdapter("pipeline.ipynb")
ks = KernelSession(nb)
runner = NotebookRunner(nb, ks)

ks.start()
nb.update_cell(0, "print('hello')")
result = runner.run_cell(0)
print(result.outputs)
nb.save()
ks.shutdown()
```

## Security

- Only `.ipynb` files are allowed
- All paths are resolved and checked against `--workspace-root`; any path outside it is rejected
- The server runs as the same user that launched it — don't point it at sensitive directories

## Requirements

- Python 3.10+
- `jupyter_client >= 8.0.0`
- A Jupyter kernel installed for your target language (e.g. `pip install ipykernel` for Python)

## License

MIT
