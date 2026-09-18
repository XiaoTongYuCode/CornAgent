"""Resource-limited subprocess for text and DOCX extraction."""

import json
import sys

from app.document_formats import document_text
from app.file_parser import _apply_linux_limits


def main():
    try:
        _apply_linux_limits()
        text = document_text(sys.stdin.buffer.read(), sys.argv[1])
        limit = int(sys.argv[2])
        result = dict(
            ok=True,
            markdown=text[:limit],
            truncated=len(text) > limit,
            parser="cornagent-document",
            parser_version="1",
            page_count=0,
        )
    except Exception:
        result = dict(ok=False, error_code="session_file_extraction_failed")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
