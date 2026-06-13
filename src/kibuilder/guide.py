"""Visual step-by-step assembly-page composer.

Combines per-stage cumulative board renders (from `render.board`) with
per-component renders (from `render.part`) into one 2000×1500 instruction
page per stage: yellow step badge + title/subtitle on the left, parts
callout panel in the top-right, board hero filling the rest.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from kibuilder import config as kbcfg

log = logging.getLogger("kibuilder.guide")

W, H = 2000, 1500
BG = "white"
BADGE_FILL = "#FFD400"
BADGE_BORDER = "#1a1a1a"
TEXT = "#1a1a1a"
SUBTEXT = "#555555"
BOX_BORDER = "#1a1a1a"
QTY_BG = "#1a1a1a"
QTY_FG = "white"

_FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int):
    for path in _FONT_CANDIDATES_BOLD:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _grid(n: int) -> tuple[int, int, int, int]:
    # Cell heights are picked so (title_h=56) + (top margin=24) + rows*ch
    # stays inside the 540px parts panel with at least ~50px of slack for
    # 2-line labels.
    if n <= 1: return 1, 1, 600, 440
    if n == 2: return 2, 1, 340, 320
    if n == 3: return 3, 1, 230, 280
    if n == 4: return 2, 2, 340, 210
    if n <= 6: return 3, 2, 230, 210
    return 4, 2, 170, 210


def _fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    s = min(max_w / img.width, max_h / img.height)
    return img.resize(
        (max(1, int(img.width * s)), max(1, int(img.height * s))),
        Image.LANCZOS,
    )


def _fit_label(pd: ImageDraw.ImageDraw, cx: int, cy: int, text: str,
               base_font, base_size: int, max_w: int, color):
    """Draw `text` centered at (cx, cy) so it fits inside `max_w` pixels.

    Strategy in order:
      1. If it already fits at full size, draw on one line.
      2. Try splitting on '_' or '-' into two lines; use if both lines fit.
      3. Shrink the font down to 12pt until it fits.
      4. Truncate with an ellipsis.
    """
    if not text:
        return

    def width(t, font):
        bb = pd.textbbox((0, 0), t, font=font)
        return bb[2] - bb[0]

    # 1) Fits as-is
    if width(text, base_font) <= max_w:
        pd.text((cx, cy), text, fill=color, font=base_font, anchor="mm")
        return

    # 2) Two-line split on _ or -
    for sep in ("_", "-"):
        if sep in text:
            parts = text.split(sep)
            mid = max(1, len(parts) // 2)
            l1 = sep.join(parts[:mid])
            l2 = sep.join(parts[mid:])
            if width(l1, base_font) <= max_w and width(l2, base_font) <= max_w:
                bb = pd.textbbox((0, 0), "Ag", font=base_font)
                h = bb[3] - bb[1]
                pd.text((cx, cy - h // 2), l1,
                        fill=color, font=base_font, anchor="mm")
                pd.text((cx, cy + h // 2 + 2), l2,
                        fill=color, font=base_font, anchor="mm")
                return

    # 3) Shrink font
    for size in range(base_size - 2, 11, -2):
        f = _load_font(size)
        if width(text, f) <= max_w:
            pd.text((cx, cy), text, fill=color, font=f, anchor="mm")
            return

    # 4) Truncate
    truncated = text
    while truncated:
        candidate = truncated + "…"
        if width(candidate, base_font) <= max_w:
            pd.text((cx, cy), candidate,
                    fill=color, font=base_font, anchor="mm")
            return
        truncated = truncated[:-1]


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw,
               max_lines: int = 3) -> list[str]:
    """Greedy word-wrap. Last line gets an ellipsis if we hit max_lines."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        test = (current + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and (current or words):
        # If we truncated, mark the last line
        last = lines[-1]
        while last:
            bb = draw.textbbox((0, 0), last + "…", font=font)
            if (bb[2] - bb[0]) <= max_width:
                lines[-1] = last + "…"
                break
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    return lines


def _parts_panel(parts: list[kbcfg.StagePart],
                 components_dir: Path,
                 panel_w: int, panel_h: int,
                 font_label, font_qty) -> Image.Image:
    panel = Image.new("RGBA", (panel_w, panel_h), (255, 255, 255, 255))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(
        [2, 2, panel_w - 3, panel_h - 3],
        radius=18, outline=BOX_BORDER, width=4,
    )
    title_h = 56
    pd.rectangle([4, 4, panel_w - 5, title_h], fill="#f5f5f5")
    pd.text(
        (panel_w / 2, title_h / 2 + 2), "PARTS TO ADD",
        fill="#666", font=font_label, anchor="mm",
    )
    if not parts:
        return panel

    cols, rows, cw, ch = _grid(len(parts))
    grid_w = cols * cw
    grid_x0 = (panel_w - grid_w) // 2
    grid_y0 = title_h + 24

    for i, p in enumerate(parts):
        r, c = divmod(i, cols)
        cx = grid_x0 + c * cw
        cy = grid_y0 + r * ch
        png = components_dir / f"{p.key}.png"
        if png.exists():
            comp = Image.open(png).convert("RGBA")
            comp = _fit(comp, cw - 20, ch - 60)
            ix = cx + (cw - comp.width) // 2
            iy = cy + (ch - 60 - comp.height) // 2 + 4
            panel.paste(comp, (ix, iy), comp)
        else:
            pd.text(
                (cx + cw / 2, cy + ch / 2 - 30), f"[{p.key}]",
                fill="red", font=font_label, anchor="mm",
            )
        if p.label:
            # Anchor 2 lines worth of label inside the cell; ~32px from the
            # cell bottom so multi-line labels don't poke past the panel.
            _fit_label(
                pd,
                cx + cw // 2, cy + ch - 32, p.label,
                font_label, base_size=24,
                max_w=cw - 12, color=TEXT,
            )
        if p.qty > 1:
            qtext = f"×{p.qty}"
            bb = pd.textbbox((0, 0), qtext, font=font_qty)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            bw, bh = tw + 22, th + 14
            bx = cx + cw - bw - 10
            by = cy + 10
            pd.rounded_rectangle(
                [bx, by, bx + bw, by + bh],
                radius=bh // 2, fill=QTY_BG,
            )
            pd.text(
                (bx + bw / 2, by + bh / 2 + 1), qtext,
                fill=QTY_FG, font=font_qty, anchor="mm",
            )

    return panel


def compose_page(stage: kbcfg.StageSpec,
                 board_img: Path,
                 components_dir: Path,
                 out_path: Path) -> Path:
    page = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(page)

    fb = _load_font(160)
    ft = _load_font(70)
    fs = _load_font(36)
    fl = _load_font(24)
    fq = _load_font(32)

    bs = 200
    bx, by = 60, 60
    draw.rounded_rectangle(
        [bx, by, bx + bs, by + bs], radius=26,
        fill=BADGE_FILL, outline=BADGE_BORDER, width=6,
    )
    draw.text(
        (bx + bs / 2, by + bs / 2 + 6), str(stage.n),
        fill=TEXT, font=fb, anchor="mm",
    )

    panel_w, panel_h = 760, 540
    panel_x = W - panel_w - 60
    panel_y = 50

    tx, ty = bx + bs + 40, by + 22

    # Title — wrap up to 2 lines so a long title doesn't slide under the
    # parts panel. Available width = up to where the panel starts (when
    # present), otherwise the full right margin.
    title_max_w = panel_x - tx - 30 if stage.parts else (W - tx - 60)
    title_lines = _wrap_text(
        stage.title, ft, title_max_w, draw, max_lines=2,
    ) or [stage.title]
    title_line_h = int(getattr(ft, "size", 70) * 1.15)
    ty_cursor = ty
    for line in title_lines:
        draw.text((tx, ty_cursor), line, fill=TEXT, font=ft)
        ty_cursor += title_line_h
    title_bottom = ty_cursor

    sub_bottom = title_bottom + 16
    if stage.sub:
        sub_max_w = panel_x - tx - 30 if stage.parts else (W - tx - 60)
        sub_lines = _wrap_text(stage.sub, fs, sub_max_w, draw, max_lines=3)
        line_h = int(getattr(fs, "size", 36) * 1.18)
        sy = title_bottom + 16
        for line in sub_lines:
            draw.text((tx, sy), line, fill=SUBTEXT, font=fs)
            sy += line_h
        sub_bottom = sy

    if stage.parts:
        panel = _parts_panel(
            stage.parts, components_dir, panel_w, panel_h, fl, fq,
        )
        page.paste(panel, (panel_x, panel_y), panel)
        main_top = max(panel_y + panel_h + 30, sub_bottom + 30)
    else:
        main_top = max(300, sub_bottom + 30)

    if board_img and board_img.exists():
        main = Image.open(board_img).convert("RGB")
        main_max_w = W - 140
        main_max_h = H - main_top - 60
        main = _fit(main, main_max_w, main_max_h)
        mx = (W - main.width) // 2
        my = main_top + max(0, (main_max_h - main.height) // 2)
        page.paste(main, (mx, my))
    else:
        draw.text(
            (W / 2, (H + main_top) / 2), "(board image missing)",
            fill="#cc0000", font=ft, anchor="mm",
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(out_path, quality=88, optimize=True)
    log.info("page %d → %s", stage.n, out_path.name)
    return out_path


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower()).strip("_")[:30] or "stage"


def build_pages(cfg: kbcfg.Config,
                parts_dir: Path,
                boards_dir: Path,
                out_dir: Path,
                progress=None) -> list[Path]:
    """Compose one page per stage. Returns list of written paths.

    `progress(idx, total, stage)` is called per stage if provided.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stages = sorted(cfg.stages, key=lambda s: s.n)
    total = len(stages)
    written: list[Path] = []
    for i, s in enumerate(stages, 1):
        if progress is not None:
            progress(i, total, s)
        board = boards_dir / f"{s.n:02d}.jpg"
        out = out_dir / f"{s.n:02d}_{_slug(s.title)}.jpg"
        compose_page(s, board, parts_dir, out)
        written.append(out)
    return written


def build_markdown(cfg: kbcfg.Config,
                   pages: list[Path],
                   out_path: Path,
                   *,
                   title: str | None = None,
                   pdf_path: Path | None = None) -> Path:
    """Emit a GitHub-viewable Markdown assembly guide.

    Image paths in the markdown are written *relative to the markdown
    file's directory*, so the resulting `.md` renders correctly when
    committed alongside its images in a repository.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stages = sorted(cfg.stages, key=lambda s: s.n)
    pages_by_n = {
        int(p.name[:2]): p for p in pages if p.name[:2].isdigit()
    }

    pcb_stem = Path(cfg.project.pcb).stem if cfg.project.pcb else "Project"
    h1 = title or f"{pcb_stem} — Assembly Guide"

    lines: list[str] = []
    lines.append(f"# {h1}")
    lines.append("")
    lines.append(
        f"Hand-solder the board **shortest components first, tallest "
        f"last** so the PCB lays flat through each step. {len(stages)} "
        f"stage(s) below; the cumulative render at each step shows the "
        f"board after that stage is finished."
    )
    lines.append("")
    if pdf_path is not None:
        rel = _relpath(pdf_path, out_path.parent)
        lines.append(f"📄 **[Printable single-PDF guide]({rel})**")
        lines.append("")
    lines.append("## Stages")
    lines.append("")
    for s in stages:
        lines.append(f"- [{s.n}. {s.title}](#{_anchor(s.n, s.title)})"
                     + (f" — {len(s.parts)} part(s)" if s.parts else ""))
    lines.append("")
    lines.append("---")
    lines.append("")

    for s in stages:
        lines.append(f"### {s.n}. {s.title}")
        lines.append("")
        if s.sub:
            lines.append(f"_{s.sub}_")
            lines.append("")
        page = pages_by_n.get(s.n)
        if page and page.exists():
            rel = _relpath(page, out_path.parent)
            lines.append(f"![Stage {s.n} — {s.title}]({rel})")
            lines.append("")
        if s.parts:
            lines.append("| Qty | Component | Label |")
            lines.append("|----:|-----------|-------|")
            for p in s.parts:
                label = (p.label or "").replace("|", "\\|")
                lines.append(
                    f"| ×{p.qty} | `{p.key}` | {label} |"
                )
            lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    src_name = Path(cfg.source_path).name if cfg.source_path else "config.yaml"
    logo = (
        "https://raw.githubusercontent.com/mattnakamura/kibuilder/"
        "main/resources/icon_1024.png"
    )
    lines.append(
        f'<sub><img src="{logo}" alt="kibuilder" width="16" '
        f'align="absmiddle"> Generated by '
        f"[kibuilder](https://github.com/mattnakamura/kibuilder) "
        f"from `{src_name}`.</sub>"
    )
    lines.append("")

    out_path.write_text("\n".join(lines))
    log.info("markdown → %s  (%d stages)", out_path.name, len(stages))
    return out_path


_ANCHOR_RE = re.compile(r"[^a-z0-9 -]")


def _anchor(n: int, title: str) -> str:
    """GitHub-style heading anchor for `### N. Title`."""
    base = f"{n} {title.lower()}"
    base = _ANCHOR_RE.sub("", base)
    return base.replace(" ", "-")


def _relpath(target: Path, start: Path) -> str:
    """POSIX-style relative path so markdown renders on every OS."""
    try:
        rel = Path(target).resolve().relative_to(Path(start).resolve())
        return rel.as_posix()
    except ValueError:
        import os.path as _osp
        return _osp.relpath(str(target), str(start)).replace("\\", "/")


def build_pdf(pages: list[Path], out_path: Path,
              resolution_dpi: float = 150.0) -> Path:
    """Combine page JPGs into one multi-page landscape PDF.

    Page dimensions follow the source images' pixel size at the given DPI;
    since pages are rendered 2000×1500 (4:3), the PDF is landscape by
    construction.
    """
    if not pages:
        raise ValueError("no pages to bundle into PDF")
    imgs = [Image.open(p).convert("RGB") for p in pages]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    imgs[0].save(
        out_path, "PDF",
        save_all=True,
        append_images=imgs[1:],
        resolution=resolution_dpi,
    )
    log.info("PDF → %s  (%d pages)", out_path.name, len(pages))
    return out_path
