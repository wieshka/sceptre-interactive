"""
``list resources -i``: each stack's resources as a table, like the Resources
tab of the CloudFormation console, with physical IDs linked to their console
pages (terminal hyperlinks).
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional

import botocore.exceptions
from rich.console import Console, Group, RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text

from sceptre_interactive.console_links import console_url, stack_url

MAX_WORKERS = 10

STATUS_STYLE = {"COMPLETE": "green", "IN_PROGRESS": "cyan", "FAILED": "red"}


@dataclass
class StackResources:
    name: str
    external_name: str
    region: Optional[str]
    resources: List[dict] = field(default_factory=list)
    exists: bool = True
    error: Optional[str] = None


def fetch_stack_resources(stack) -> StackResources:
    """All resources of a stack via the paginated ListStackResources API."""
    connection_manager = stack.connection_manager
    region = stack.region or getattr(connection_manager, "region", None)
    result = StackResources(stack.name, stack.external_name, region)
    kwargs = {"StackName": stack.external_name}
    try:
        while True:
            response = connection_manager.call(
                service="cloudformation",
                command="list_stack_resources",
                kwargs=kwargs,
            )
            result.resources.extend(response.get("StackResourceSummaries", []))
            next_token = response.get("NextToken")
            if not next_token:
                break
            kwargs = {"StackName": stack.external_name, "NextToken": next_token}
    except botocore.exceptions.ClientError as error:
        if error.response["Error"]["Message"].endswith("does not exist"):
            result.exists = False
        else:
            result.error = error.response["Error"]["Message"]
    return result


def fetch_all(stacks) -> List[StackResources]:
    """Fetch resources for many stacks concurrently, keeping their order."""
    stacks = list(stacks)
    if not stacks:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(stacks))) as pool:
        return list(pool.map(fetch_stack_resources, stacks))


def _status_style(status: str) -> str:
    for suffix, style in STATUS_STYLE.items():
        if status.endswith(suffix) or f"_{suffix}_" in status:
            return style
    return "dim"


def _linked(text: str, url: Optional[str], show_urls: bool) -> Text:
    if not url:
        return Text(text)
    if show_urls:
        return Text.assemble(text, "\n", Text(url, style="dim"))
    return Text(text, style=Style(link=url, underline=True, color="blue"))


def stack_table(stack: StackResources, show_urls: bool = False) -> RenderableType:
    url = stack_url(stack.external_name, stack.region) if stack.region else None
    title = Text()
    if url and not show_urls:
        title.append_text(_linked(stack.name, url, False))
    else:
        title.append(stack.name)
    title.stylize("bold")
    title.append(f"  {stack.external_name}", style="dim")
    if stack.region:
        title.append(f"  {stack.region}", style="dim")
    if url and show_urls:
        title.append(f"\n{url}", style="dim")

    if stack.error:
        return Group(title, Text(f"  {stack.error}", style="red"), Text(""))
    if not stack.exists:
        return Group(title, Text("  not deployed", style="dim"), Text(""))

    table = Table(
        title=title,
        title_justify="left",
        show_lines=False,
        header_style="bold",
        expand=False,
    )
    table.add_column("Logical ID", no_wrap=True)
    table.add_column("Physical ID", overflow="fold")
    table.add_column("Type", style="dim", no_wrap=True)
    table.add_column("Status", no_wrap=True)

    for resource in sorted(stack.resources, key=lambda r: r["LogicalResourceId"]):
        physical_id = resource.get("PhysicalResourceId", "")
        resource_type = resource.get("ResourceType", "")
        status = resource.get("ResourceStatus", "")
        url = console_url(resource_type, physical_id, stack.region or "")
        table.add_row(
            resource["LogicalResourceId"],
            _linked(physical_id, url, show_urls),
            resource_type,
            Text(status, style=_status_style(status)),
        )
    if not stack.resources:
        table.add_row(Text("no resources", style="dim"), "", "", "")
    return table


def render_resources(
    stacks: List[StackResources], console: Console, show_urls: bool = False
) -> None:
    for stack in stacks:
        console.print(stack_table(stack, show_urls))
    linked = sum(
        1
        for stack in stacks
        for r in stack.resources
        if console_url(
            r.get("ResourceType", ""),
            r.get("PhysicalResourceId", ""),
            stack.region or "",
        )
    )
    total = sum(len(s.resources) for s in stacks)
    if total and not show_urls:
        console.print(
            Text(
                f"{total} resources in {len(stacks)} stacks, {linked} linked to the "
                "AWS console. Cmd/Ctrl-click a Physical ID to open it "
                "(use --urls if your terminal doesn't support links).",
                style="dim",
            )
        )
