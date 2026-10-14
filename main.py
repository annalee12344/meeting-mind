"""
Meeting Mind — Main Entry Point

A 2-pass LLM pipeline for extracting structured meeting intelligence from
Vietnamese meeting transcripts using Google Gemini API.

Pipeline Flow:
  Read File -> Preprocess (Step 0) -> Extract Utterances (Step 1)
            -> Resolve Progression (Step 2) -> Validate Evidence (Step 3)
            -> Save Structured JSON & Display Visual Summary

Usage:
  python main.py <transcript_file> [--output <output_file>] [--verbose]
"""
import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
from models.output import MeetingOutput
from pipeline.preprocessor import preprocess
from pipeline.extractor import Extractor
from pipeline.resolver import Resolver
from pipeline.validator import Validator

# Setup rich console for styled terminal output
console = Console()

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger("meeting_mind")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Meeting Mind: Extract structured data from Vietnamese meeting transcripts."
    )
    parser.add_argument(
        "transcript_file",
        type=str,
        help="Path to the input transcript text file (.txt).",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Path to save the output JSON file. Defaults to output/ directory.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (shows intermediate Step 1 candidate utterances).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help=f"Fuzzy match similarity threshold (0-100). Default: {config.FUZZY_MATCH_THRESHOLD}",
    )
    return parser.parse_args()


def display_intermediate_results(extraction_result) -> None:
    """Print intermediate candidate utterances from Step 1 in a table."""
    table = Table(
        title="[bold cyan]Step 1: Trích xuất phát biểu ứng viên (Candidate Utterances)[/]",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("ID", style="dim", width=6)
    table.add_column("Thời gian", width=10)
    table.add_column("Người nói", width=14)
    table.add_column("Chủ đề", width=18)
    table.add_column("Loại (Type)", width=12)
    table.add_column("Vai trò (Role)", width=12)
    table.add_column("Trích dẫn (Quote)", min_width=30)

    for u in extraction_result.utterances:
        table.add_row(
            u.id,
            u.timestamp or "N/A",
            u.speaker,
            u.topic,
            u.type.value,
            u.role.value,
            u.quote,
        )

    console.print(table)
    console.print()


def display_final_summary(output: MeetingOutput, output_path: Path) -> None:
    """Display the structured final results and verification status."""
    # Meeting Summary Panel
    console.print(
        Panel(
            Text(output.meeting_summary, style="italic green"),
            title="[bold yellow]Tóm tắt cuộc họp (Executive Summary)[/]",
            border_style="yellow",
        )
    )

    # Participants
    participants_str = ", ".join(output.participants) if output.participants else "Không xác định"
    console.print(f"[bold cyan]Người tham gia:[/] {participants_str}\n")

    # Overview Table
    summary_table = Table(
        title="[bold green]Tổng hợp kết quả xử lý (Structured Items)[/]",
        show_header=True,
        header_style="bold blue",
    )
    summary_table.add_column("Hạng mục", width=25)
    summary_table.add_column("Số lượng", justify="center", width=10)
    summary_table.add_column("Cần xem xét (Needs Review)", justify="center", width=25)

    def count_needs_review(items) -> int:
        return sum(1 for item in items if getattr(item, "needs_review", False))

    summary_table.add_row(
        "Quyết định (Decisions)",
        str(len(output.decisions)),
        f"[red]{count_needs_review(output.decisions)}[/]" if count_needs_review(output.decisions) else "[green]0[/]",
    )
    summary_table.add_row(
        "Việc cần làm (Action Items)",
        str(len(output.action_items)),
        f"[red]{count_needs_review(output.action_items)}[/]" if count_needs_review(output.action_items) else "[green]0[/]",
    )
    summary_table.add_row(
        "Khó khăn / Rủi ro (Blockers)",
        str(len(output.blockers)),
        f"[red]{count_needs_review(output.blockers)}[/]" if count_needs_review(output.blockers) else "[green]0[/]",
    )
    summary_table.add_row(
        "Yêu cầu / Góp ý (Requests)",
        str(len(output.requests)),
        f"[red]{count_needs_review(output.requests)}[/]" if count_needs_review(output.requests) else "[green]0[/]",
    )
    summary_table.add_row(
        "Chưa giải quyết (Unresolved)",
        str(len(output.unresolved_items)),
        f"[red]{count_needs_review(output.unresolved_items)}[/]" if count_needs_review(output.unresolved_items) else "[green]0[/]",
    )

    console.print(summary_table)
    console.print()

    # Decisions Detail Table
    if output.decisions:
        dec_table = Table(
            title="[bold green]Chi tiết quyết định & Tiến trình thảo luận[/]",
            show_header=True,
            header_style="bold green",
        )
        dec_table.add_column("Mã", width=6)
        dec_table.add_column("Chủ đề", width=20)
        dec_table.add_column("Kết luận cuối cùng", width=35)
        dec_table.add_column("Trạng thái", width=12)
        dec_table.add_column("Lịch sử thay đổi", min_width=25)
        dec_table.add_column("Xác thực", width=10)

        for d in output.decisions:
            hist_str = "\n".join([f"- {h.value} ({h.status.value})" for h in d.history]) or "N/A"
            status_style = "green" if d.status.value == "confirmed" else "yellow"
            review_str = "[bold red]CẦN XEM LẠI[/]" if d.needs_review else "[bold green]HỢP LỆ[/]"

            dec_table.add_row(
                d.item_id,
                d.topic,
                d.final_value,
                f"[{status_style}]{d.status.value}[/]",
                hist_str,
                review_str,
            )
        console.print(dec_table)
        console.print()

    # Action Items Detail Table
    if output.action_items:
        ai_table = Table(
            title="[bold blue]Chi tiết việc cần làm (Action Items)[/]",
            show_header=True,
            header_style="bold blue",
        )
        ai_table.add_column("Mã", width=6)
        ai_table.add_column("Nhiệm vụ", width=35)
        ai_table.add_column("Người nhận", width=15)
        ai_table.add_column("Hạn chót", width=15)
        ai_table.add_column("Xác thực", width=10)

        for a in output.action_items:
            review_str = "[bold red]CẦN XEM LẠI[/]" if a.needs_review else "[bold green]HỢP LỆ[/]"
            ai_table.add_row(
                a.item_id,
                a.task,
                a.assignee or "Chưa phân công",
                a.deadline or "Chưa rõ",
                review_str,
            )
        console.print(ai_table)
        console.print()

    # Warnings for items needing review
    warnings: list[str] = []
    for d in output.decisions:
        if d.needs_review:
            warnings.append(f"Quyết định [bold]{d.item_id}[/] ({d.topic}): Bằng chứng không khớp hoặc thiếu dữ liệu.")
    for a in output.action_items:
        if a.needs_review:
            warnings.append(f"Action Item [bold]{a.item_id}[/] ({a.task}): Bằng chứng chưa được xác minh.")
    for b in output.blockers:
        if b.needs_review:
            warnings.append(f"Blocker [bold]{b.item_id}[/] ({b.issue}): Bằng chứng chưa được xác minh.")
    for r in output.requests:
        if r.needs_review:
            warnings.append(f"Request [bold]{r.item_id}[/] ({r.content}): Bằng chứng chưa được xác minh.")
    for u in output.unresolved_items:
        if u.needs_review:
            warnings.append(f"Unresolved [bold]{u.item_id}[/] ({u.topic}): Bằng chứng chưa được xác minh.")

    if warnings:
        warn_text = "\n".join([f"• {w}" for w in warnings])
        console.print(
            Panel(
                Text.from_markup(warn_text),
                title="[bold red]Cảnh báo kiểm tra bằng chứng (Validation Warnings)[/]",
                border_style="red",
            )
        )
        console.print()

    console.print(f"[bold green]✔ Kết quả JSON đã được lưu thành công tại:[/] [underline cyan]{output_path}[/]\n")


def main() -> int:
    """Main execution function."""
    args = parse_arguments()

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]MEETING MIND[/] — Trí tuệ nhân tạo phân tích biên bản cuộc họp tiếng Việt\n"
            "[dim]Kiến trúc đường ống 2-pass: Trích xuất -> Giải quyết tiến trình -> Xác minh bằng chứng[/]",
            border_style="cyan",
        )
    )
    console.print()

    # 1. Read input file
    input_path = Path(args.transcript_file)
    if not input_path.exists():
        console.print(f"[bold red]Lỗi:[/] Không tìm thấy tệp biên bản tại '{input_path.resolve()}'.", style="red")
        return 1

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except Exception as e:
        console.print(f"[bold red]Lỗi khi đọc tệp:[/] {e}", style="red")
        return 1

    if not raw_text.strip():
        console.print("[bold red]Lỗi:[/] Tệp biên bản rỗng.", style="red")
        return 1

    # 2. Check API Key
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_api_key_here":
        console.print(
            Panel(
                "[bold red]Chưa cấu hình GEMINI_API_KEY![/]\n\n"
                "Vui lòng tạo tệp [bold].env[/] trong thư mục gốc hoặc thiết lập biến môi trường:\n"
                "  [cyan]GEMINI_API_KEY=AIzaSy...[/]\n\n"
                "Bạn có thể lấy API Key miễn phí tại: [underline blue]https://aistudio.google.com/apikey[/]",
                title="[bold red]Thiếu khóa API[/]",
                border_style="red",
            )
        )
        return 1

    # 3. Pipeline Execution
    try:
        # ── Step 0: Preprocessing ──
        with console.status("[bold green]Bước 0: Tiền xử lý biên bản & đánh mã phát biểu...[/]"):
            preprocessed_transcript = preprocess(raw_text)
            num_utterances = len(preprocessed_transcript.splitlines())

        console.print(f"[bold green]✔ Bước 0 hoàn tất:[/] Đã chuẩn hóa và đánh mã {num_utterances} phát biểu.")

        # ── Step 1: Extraction ──
        with console.status("[bold green]Bước 1: Trích xuất phát biểu ứng viên (Gọi Gemini API Pass 1)...[/]"):
            extractor = Extractor()
            extraction_result = extractor.extract(preprocessed_transcript)

        console.print(
            f"[bold green]✔ Bước 1 hoàn tất:[/] Đã trích xuất {len(extraction_result.utterances)} phát biểu quan trọng."
        )

        if args.verbose:
            display_intermediate_results(extraction_result)

        # ── Step 2: Resolution ──
        with console.status("[bold green]Bước 2: Giải quyết tiến trình thảo luận & chốt kết quả (Gọi Gemini API Pass 2)...[/]"):
            resolver = Resolver()
            resolved_output = resolver.resolve(extraction_result)

        console.print(
            f"[bold green]✔ Bước 2 hoàn tất:[/] Đã tổng hợp tiến trình "
            f"({len(resolved_output.decisions)} quyết định, {len(resolved_output.action_items)} việc cần làm)."
        )

        # ── Step 3: Validation ──
        with console.status("[bold green]Bước 3: Xác minh bằng chứng nguyên văn bằng RapidFuzz...[/]"):
            validator = Validator(threshold=args.threshold)
            validated_output = validator.validate(resolved_output, raw_text)

        console.print("[bold green]✔ Bước 3 hoàn tất:[/] Đã đối chiếu bằng chứng với văn bản gốc.")
        console.print()

        # 4. Save Output JSON
        if args.output:
            out_file = Path(args.output)
        else:
            config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = config.OUTPUT_DIR / f"{input_path.stem}_{timestamp_str}.json"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(
            json.dumps(validated_output.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 5. Display Summary
        display_final_summary(validated_output, out_file)
        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Đã hủy tiến trình bởi người dùng.[/]")
        return 130
    except Exception as exc:
        console.print(f"\n[bold red]Lỗi thực thi pipeline:[/] {exc}", style="red")
        logger.exception("Chi tiết lỗi:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
