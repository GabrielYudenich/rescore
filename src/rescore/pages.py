from __future__ import annotations


def parse_page_spec(value: str) -> list[int]:
    """Parse a 1-based page specification such as ``67,70-72``."""
    pages: set[int] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start < 1 or end < 1 or end < start:
                raise ValueError(f"intervalo de páginas inválido: {item}")
            pages.update(range(start, end + 1))
        else:
            page = int(item)
            if page < 1:
                raise ValueError(f"página inválida: {page}")
            pages.add(page)
    if not pages:
        raise ValueError("nenhuma página foi informada")
    return sorted(pages)


def compact_page_spec(pages: list[int]) -> str:
    if not pages:
        return ""
    result: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        result.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    result.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(result)
