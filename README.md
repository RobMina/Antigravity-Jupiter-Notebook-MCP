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

In Antigravity, open **Settings → MCP Servers** and add:

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

Or copy the included `.antigravity/mcp.json` — Antigravity will pick it up automatically when you open this project folder.

Once connected, Antigravity discovers all tools automatically. You can then ask it things like:

> "Run the preprocess stage in pipeline.ipynb and show me the outputs"
> "Edit cell 2 in analysis.ipynb to use pandas instead of a plain list"
> "Run all cells in notebook.ipynb and tell me if any failed"

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
