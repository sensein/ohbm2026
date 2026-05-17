from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the poster layout review in headless Chromium")
    parser.add_argument("--input-html", default="data/poster_layout/proposals/layout_review.html")
    parser.add_argument("--output-dir", default="data/poster_layout/proposals/layout_review_checks")
    parser.add_argument("--proposal", action="append")
    parser.add_argument("--viewport-width", type=int, default=1600)
    parser.add_argument("--viewport-height", type=int, default=1200)
    return parser


def _file_url(path: Path) -> str:
    return f"file://{quote(str(path.resolve()))}"


def _serve_directory(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_html = Path(args.input_html)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "input_html": str(input_html.resolve()),
        "screenshots": [],
        "proposals": [],
    }

    httpd, thread = _serve_directory(input_html.parent)
    report["served_from"] = f"http://127.0.0.1:{httpd.server_address[1]}/{input_html.name}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": int(args.viewport_width), "height": int(args.viewport_height)})
            page.goto(str(report["served_from"]))
            page.wait_for_selector("[data-proposal-slug]")

            available_proposals = page.locator("[data-proposal-slug]").evaluate_all(
                """(buttons) => buttons.map((item) => ({
                    value: item.getAttribute('data-proposal-slug'),
                    label: item.textContent
                }))"""
            )
            requested = set(args.proposal or [])
            selected_proposals = [
                item for item in available_proposals if not requested or str(item.get("value")) in requested
            ]
            report["available_proposals"] = available_proposals

            for proposal in selected_proposals:
                proposal_value = str(proposal.get("value"))
                page.locator(f'[data-proposal-slug="{proposal_value}"]').click()
                page.locator("[data-color-mode]").first.wait_for(timeout=30000, state="attached")
                page.locator("#sidebar-category-selectors input[data-filter-group='categorical_primary_label']").first.wait_for(timeout=30000, state="attached")
                page.wait_for_timeout(800)
                category_counts = {
                    "categorical_primary_label": page.locator("#sidebar-category-selectors input[data-filter-group='categorical_primary_label']").count(),
                    "voyage25_label": page.locator("#sidebar-category-selectors input[data-filter-group='voyage25_label']").count(),
                    "voyage31_label": page.locator("#sidebar-category-selectors input[data-filter-group='voyage31_label']").count(),
                    "claims28_label": page.locator("#sidebar-category-selectors input[data-filter-group='claims28_label']").count(),
                }
                plot_runtime = page.locator("#block-1-plot").evaluate(
                    """(plot) => ({
                        hasOn: typeof plot.on,
                        hasData: Array.isArray(plot.data),
                        traceCount: Array.isArray(plot.data) ? plot.data.length : -1,
                        dragmode: plot?.layout?.dragmode ?? plot?._fullLayout?.dragmode ?? null,
                        yaxisScaleanchor: plot?._fullLayout?.yaxis?.scaleanchor ?? null,
                        visibleTraceIndex: Array.isArray(plot.data)
                          ? plot.data.findIndex((trace) => Array.isArray(trace.customdata) && trace.customdata.length > 0 && trace.visible !== false)
                          : -1,
                        firstCustomdata: Array.isArray(plot.data)
                          ? (() => {
                              const idx = plot.data.findIndex((trace) => Array.isArray(trace.customdata) && trace.customdata.length > 0 && trace.visible !== false);
                              return idx >= 0 ? plot.data[idx].customdata[0] : null;
                            })()
                          : null
                    })"""
                )
                page.locator("[data-color-mode='voyage25_label']").click()
                page.wait_for_timeout(400)
                detail_before = page.locator("#poster-detail-card").inner_text()
                point_probe = page.locator("#block-1-plot").evaluate(
                    """(plot) => {
                        const xaxis = plot?._fullLayout?.xaxis;
                        const yaxis = plot?._fullLayout?.yaxis;
                        if (!xaxis || !yaxis || !Array.isArray(plot?.data)) {
                          return null;
                        }
                        for (const trace of plot.data) {
                          if (trace?.visible === false || !Array.isArray(trace?.customdata) || !Array.isArray(trace?.x) || !Array.isArray(trace?.y) || !trace.customdata.length) {
                            continue;
                          }
                          const x = trace.x[0];
                          const y = trace.y[0];
                          return {
                            px: xaxis.l2p(x) + xaxis._offset,
                            py: yaxis.l2p(y) + yaxis._offset
                          };
                        }
                        return null;
                    }"""
                )
                if point_probe:
                    plot_box = page.locator("#block-1-plot").bounding_box()
                    if plot_box:
                        page.mouse.move(plot_box["x"] + float(point_probe["px"]), plot_box["y"] + float(point_probe["py"]))
                page.wait_for_timeout(500)
                inner_detail_before = detail_before
                inner_detail_after = page.locator("#poster-detail-card").inner_text()
                detail_after = inner_detail_after
                inner_detail_changed = inner_detail_after != inner_detail_before
                detail_changed = detail_after != detail_before
                marker_count = page.locator("#block-1-plot .scatterlayer .points path").count()
                detail_after_click = detail_after
                inner_detail_after_click = inner_detail_after
                click_changed = False
                near_click_changed = False
                detail_after_near_click = detail_after
                proposal_switch_click_report = {}
                if point_probe and plot_box:
                    page.mouse.click(plot_box["x"] + float(point_probe["px"]), plot_box["y"] + float(point_probe["py"]))
                    page.wait_for_timeout(500)
                    inner_detail_after_click = page.locator("#poster-detail-card").inner_text()
                    detail_after_click = inner_detail_after_click
                    click_changed = detail_after_click != detail_before
                    page.mouse.click(
                        plot_box["x"] + float(point_probe["px"]) + 14,
                        plot_box["y"] + float(point_probe["py"]) + 14,
                    )
                    page.wait_for_timeout(500)
                    detail_after_near_click = page.locator("#poster-detail-card").inner_text()
                    near_click_changed = detail_after_near_click != detail_before
                    other_proposal = next(
                        (item for item in available_proposals if str(item.get("value")) != proposal_value),
                        None,
                    )
                    if other_proposal is not None:
                        original_point = {"x": plot_box["x"] + float(point_probe["px"]), "y": plot_box["y"] + float(point_probe["py"])}
                        original_click_detail = detail_after_click
                        page.locator(f'[data-proposal-slug="{other_proposal["value"]}"]').click()
                        page.wait_for_timeout(900)
                        page.mouse.click(original_point["x"], original_point["y"])
                        page.wait_for_timeout(500)
                        switched_detail = page.locator("#poster-detail-card").inner_text()
                        proposal_switch_click_report = {
                            "switched_to": str(other_proposal["value"]),
                            "detail_after_original_click": original_click_detail,
                            "detail_after_switched_click": switched_detail,
                            "same_detail_after_switch": switched_detail == original_click_detail,
                        }
                        page.locator(f'[data-proposal-slug="{proposal_value}"]').click()
                        page.wait_for_timeout(900)

                # Simulate a drag selection in block 1, then inspect one- and two-double-click reset behavior.
                drag_box = page.locator("#block-1-plot .nsewdrag").bounding_box()
                selection_report = {
                    "after_drag": {},
                    "after_one_doubleclick": {},
                    "after_two_doubleclicks": {},
                }
                post_sequence_near_click_changed = False
                detail_after_sequence_near_click = detail_after_near_click
                if drag_box:
                    zoom_button = page.locator("#block-1-plot .modebar-btn[data-title='Zoom']")
                    if zoom_button.count():
                        zoom_button.first.click()
                        page.wait_for_timeout(250)
                        zoom_start_x = drag_box["x"] + drag_box["width"] * 0.15
                        zoom_start_y = drag_box["y"] + drag_box["height"] * 0.18
                        zoom_end_x = drag_box["x"] + drag_box["width"] * 0.55
                        zoom_end_y = drag_box["y"] + drag_box["height"] * 0.58
                        page.mouse.move(zoom_start_x, zoom_start_y)
                        page.mouse.down()
                        page.mouse.move(zoom_end_x, zoom_end_y, steps=12)
                        page.mouse.up()
                        page.wait_for_timeout(600)
                    lasso_button = page.locator("#block-1-plot .modebar-btn[data-title='Lasso Select']")
                    if lasso_button.count():
                        lasso_button.first.click()
                        page.wait_for_timeout(250)
                    start_x = drag_box["x"] + drag_box["width"] * 0.30
                    start_y = drag_box["y"] + drag_box["height"] * 0.30
                    end_x = drag_box["x"] + drag_box["width"] * 0.62
                    end_y = drag_box["y"] + drag_box["height"] * 0.62
                    page.mouse.move(start_x, start_y)
                    page.mouse.down()
                    page.mouse.move(end_x, end_y, steps=12)
                    page.mouse.up()
                    page.wait_for_timeout(700)

                    selection_report["after_drag"] = page.locator("#block-1-plot").evaluate(
                        """(plot) => ({
                            selectionOverlayCount: Array.isArray(plot?.layout?.selections) ? plot.layout.selections.length : 0,
                            selectedTraceCount: Array.isArray(plot?.data)
                              ? plot.data.filter((trace) => Array.isArray(trace?.selectedpoints) && trace.selectedpoints.length > 0).length
                              : 0,
                            selectedPointCount: Array.isArray(plot?.data)
                              ? plot.data.reduce((acc, trace) => acc + (Array.isArray(trace?.selectedpoints) ? trace.selectedpoints.length : 0), 0)
                              : 0
                        })"""
                    )

                    page.mouse.dblclick(end_x, end_y)
                    page.wait_for_timeout(700)
                    selection_report["after_one_doubleclick"] = page.locator("#block-1-plot").evaluate(
                        """(plot) => ({
                            selectionOverlayCount: Array.isArray(plot?.layout?.selections) ? plot.layout.selections.length : 0,
                            selectedTraceCount: Array.isArray(plot?.data)
                              ? plot.data.filter((trace) => Array.isArray(trace?.selectedpoints) && trace.selectedpoints.length > 0).length
                              : 0,
                            selectedPointCount: Array.isArray(plot?.data)
                              ? plot.data.reduce((acc, trace) => acc + (Array.isArray(trace?.selectedpoints) ? trace.selectedpoints.length : 0), 0)
                              : 0
                        })"""
                    )

                    page.mouse.dblclick(end_x, end_y)
                    page.wait_for_timeout(700)
                    selection_report["after_two_doubleclicks"] = page.locator("#block-1-plot").evaluate(
                        """(plot) => ({
                            selectionOverlayCount: Array.isArray(plot?.layout?.selections) ? plot.layout.selections.length : 0,
                            selectedTraceCount: Array.isArray(plot?.data)
                              ? plot.data.filter((trace) => Array.isArray(trace?.selectedpoints) && trace.selectedpoints.length > 0).length
                              : 0,
                            selectedPointCount: Array.isArray(plot?.data)
                              ? plot.data.reduce((acc, trace) => acc + (Array.isArray(trace?.selectedpoints) ? trace.selectedpoints.length : 0), 0)
                              : 0
                        })"""
                    )
                    if point_probe and plot_box:
                        page.mouse.click(
                            plot_box["x"] + float(point_probe["px"]) + 14,
                            plot_box["y"] + float(point_probe["py"]) + 14,
                        )
                        page.wait_for_timeout(500)
                        detail_after_sequence_near_click = page.locator("#poster-detail-card").inner_text()
                        post_sequence_near_click_changed = detail_after_sequence_near_click != detail_before

                screenshot_path = output_dir / f"{proposal_value}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)

                report["screenshots"].append(str(screenshot_path.resolve()))
                report["proposals"].append(
                    {
                        "value": proposal_value,
                        "label": proposal.get("label"),
                        "category_option_counts": {key: int(value) for key, value in category_counts.items()},
                        "plot_runtime": plot_runtime,
                        "marker_count": marker_count,
                        "detail_changed_on_click": detail_changed,
                        "inner_detail_changed_on_hover": inner_detail_changed,
                        "detail_before": detail_before,
                        "detail_after": detail_after,
                        "inner_detail_before": inner_detail_before,
                        "inner_detail_after": inner_detail_after,
                        "detail_after_click": detail_after_click,
                        "inner_detail_after_click": inner_detail_after_click,
                        "detail_changed_on_marker_click": click_changed,
                        "detail_changed_on_near_click": near_click_changed,
                        "detail_after_near_click": detail_after_near_click,
                        "proposal_switch_click_report": proposal_switch_click_report,
                        "detail_changed_on_post_sequence_near_click": post_sequence_near_click_changed,
                        "detail_after_post_sequence_near_click": detail_after_sequence_near_click,
                        "selection_report": selection_report,
                        "screenshot": str(screenshot_path.resolve()),
                    }
                )

            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1.0)

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
