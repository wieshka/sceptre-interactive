# Sceptre Interactive Plugin

A live progress display for [Sceptre](https://github.com/Sceptre/sceptre),
in the style of `docker pull`, instead of a scrolling log of CloudFormation
events.

```text
sceptre launch  1/6 done  2 running  00:42
✔ network/vpc       ━━━━━━━━━━━━━━━━━━━━ CREATE_COMPLETE           00:21
⠋ network/subnets   ━━━━━━━━━━━━         CREATE_IN_PROGRESS 3/5    00:19
    ↳ SubnetC       AWS::EC2::Subnet     CREATE_IN_PROGRESS
    ↳ RouteAssocA   AWS::EC2::SubnetRou… CREATE_IN_PROGRESS
⠋ security/kms      ━━━━━━━━━━           CREATE_IN_PROGRESS 1/2    00:19
⧗ app/database                           waiting on dependencies
⧗ app/queue                              waiting on dependencies
⧗ app/service                            waiting on dependencies
security/kms - Creating Stack
```

- One line per stack: spinner, progress bar, CloudFormation status, elapsed time
- The resources currently changing are listed under each running stack
- Stacks waiting on a dependency batch are shown as such
- Failure reasons are shown on the stack's line and in the closing summary
- Sceptre's normal log lines appear in a short footer instead of scrolling past

## Status

Local testing. Sceptre has no plugin hook for CLI options yet, so the plugin
installs a `sceptre-interactive` command: the normal `sceptre` CLI with
`-i/--interactive` added. It works with the released Sceptre (4.7+). It also
exposes `sceptre_interactive:register` under a `sceptre.cli.plugins` entry
point, so plain `sceptre -i` would work once Sceptre loads such plugins.

## Installation

Requires Python 3.10+.

```bash
pip install "sceptre-interactive-plugin @ git+https://github.com/wieshka/sceptre-interactive-plugin"
```

## Usage

`-i` works on the root command or on `create`, `update`, `launch` and `delete`:

```bash
sceptre-interactive -i launch dev
sceptre-interactive launch dev --interactive
```

Without `-i`, `sceptre-interactive` behaves exactly like `sceptre`, so you can
alias it:

```bash
alias sceptre=sceptre-interactive
```

Confirmation prompts work as usual; the live display starts after them. When
output isn't a terminal (CI, piping to a file), `-i` falls back to Sceptre's
normal log output. `--no-colour` is respected.

## Try it without AWS

```bash
sceptre-interactive-demo            # live display over a simulated 6-stack launch
sceptre-interactive-demo --fail     # app/service fails and rolls back
sceptre-interactive-demo --classic  # the same run with Sceptre's normal log output
sceptre-interactive-demo --speed 3  # faster
```

The demo runs Sceptre's real plan executor and logging. Only the AWS calls are
simulated, and they log events in the same format Sceptre does.

## How it works

With `-i`, the plugin wraps Sceptre's `SceptrePlanExecutor` while the command
runs:

1. When a plan starts executing, it builds the stack list from the plan's
   dependency batches and opens a [Rich](https://github.com/Textualize/rich)
   live display.
2. It notes when each stack starts and finishes, and the result.
3. It temporarily swaps Sceptre's log handler for one that parses the
   CloudFormation event lines Sceptre logs (`<stack> <resource> <type>
   <status> <reason>`) into per-stack and per-resource state.
4. When the plan finishes, it restores the original handler and prints the
   final table and a summary.

Sceptre's code isn't modified, and nothing changes unless `-i` is passed.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
black --check sceptre_interactive tests
pytest --cov=sceptre_interactive
```

On macOS with Python 3.13, if `import sceptre_interactive` fails inside the
venv, run `chflags -R nohidden .venv`. Python 3.13 skips `.pth` files that
have the macOS hidden flag.

## License

Apache 2.0. See [LICENSE](LICENSE).
