"""Cohort selection and comparison rules for the Posts plot."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from .derived import number


def summarize_post_portfolio(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("post_type"), row.get("audience"))].append(row)
    cohort = max(groups.values(), key=len, default=[])
    lenses = {}
    for mode in ("staying", "yield", "sharing", "likes", "comments", "restacks", "tail"):
        x_field = "lifetime_views" if mode in {"sharing", "likes", "comments", "restacks"} else "views"
        y_field = {"staying": "later_week_share", "yield": "signup_yield",
                   "sharing": "share_rate", "likes": "likes_rate", "comments": "comments_rate",
                   "restacks": "restacks_rate", "tail": "later_views"}[mode]
        minimum = 1000 if x_field == "lifetime_views" else 100
        eligible = [row for row in cohort if (number(row.get(x_field)) or 0) >= minimum
                    and number(row.get(y_field)) is not None and number(row[y_field]) >= 0]
        middle_x = median(number(row[x_field]) for row in eligible) if eligible else None
        middle_y = median(number(row[y_field]) for row in eligible) if eligible else None
        ids = [str(row["id"]) for row in eligible]
        standouts = ([str(row["id"]) for row in eligible
                      if mode in {"staying", "yield"} and number(row[x_field]) >= middle_x
                      and number(row[y_field]) >= middle_y] if eligible else [])
        if mode == "staying":
            count = sum(number(row.get("later_week_share")) >= .5 for row in eligible)
            insight = ("After launch day", f"{count} of {len(eligible)} comparable posts received at least half "
                       "their first-week views on days 2–7. Their reach continued beyond launch day.")
        elif mode == "yield":
            count = sum((number(row.get("signups")) or 0) > 0 for row in eligible)
            insight = ("Reader growth", f"{count} of {len(eligible)} comparable posts brought in at least one "
                       "signup during week one. Compare rates alongside the underlying counts.")
        elif mode == "sharing":
            insight = ("Reader sharing", f"The median comparable post earned {middle_y:.1f} recorded shares "
                       "per 1,000 lifetime views. Open high-rate posts to inspect their distribution.") if eligible else None
        elif mode in {"likes", "comments", "restacks"}:
            insight = ("Reader response", f"The median comparable post received {middle_y:.1f} {mode} "
                       "per 1,000 lifetime views. Compare counts and publication dates before drawing conclusions.") if eligible else None
        else:
            delayed = max(eligible, key=lambda row: number(row.get("later_multiple")) or 0, default=None)
            insight = ("Later discovery", f"{delayed['title']} has {delayed['later_views']:,} views after its "
                       f"first week, {delayed['later_multiple']:.1f}× its first-week total. Publication dates matter here.") if delayed and delayed.get("later_multiple") is not None else None
        lenses[mode] = {
            "eligible_ids": ids,
            "median_x": middle_x,
            "median_y": middle_y,
            "standout_ids": standouts,
            "reach_multiple": {str(row["id"]): number(row[x_field]) / middle_x
                               for row in eligible} if middle_x else {},
            "insight": {"label": insight[0], "text": insight[1]} if insight else None,
        }
    return {"cohort_size": len(cohort), "other_types": len(rows) - len(cohort),
            "lenses": lenses}
