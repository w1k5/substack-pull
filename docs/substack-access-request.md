# Supported access request for Clearview

**Status:** Draft for review; not sent
**Prepared:** November 5, 2026

## Why this is needed

Clearview is a local analytics dashboard and optional MCP companion for writers to understand their own publication, posts, and Notes. Its Mac sign-in proof of concept can reuse a writer's Substack browser session, but that is not a supported authorization route for distribution.

The [official Substack AI connector](https://support.substack.com/hc/en-us/articles/50834026608916-How-to-connect-Substack-to-your-AI-Assistant) has a writer-friendly approval flow but is limited to eligible Bestseller publication admins and read-only publication data; it excludes Notes activity and Note posting. The [developer API terms](https://substack.com/api-tos) describe public creator and publication profile data, not private owner analytics. A [publication export](https://support.substack.com/hc/en-us/articles/360037466012-How-do-I-export-my-posts) may support a useful offline subset, but its coverage and refresh behavior need to be checked.

## Request to Substack

The appropriate starting point is [Substack support](https://substack.com/contact). Ask whether Substack offers, or would approve, a writer-authorized integration with:

1. **Read access to owner analytics:** publication traffic and subscriber source history; per-post views, engagement, subscriber attribution, and time series; per-Note impressions, audience/source breakdowns, engagement, and outbound clicks.
2. **Optional Note planning access:** list a writer's Note drafts and scheduled Notes, create an unpublished draft, and schedule or reschedule it only after an explicit user action. No immediate publication is needed.
3. **Delegated sign-in:** a Substack-hosted approval flow with scoped, revocable credentials so the app never needs a full browser session or copied cookie.
4. **Operational guidance:** eligibility, permitted caching and local storage, refresh limits, rate limits, commercial distribution, and whether an optional local MCP can show the same writer-owned records to the writer's chosen AI assistant.

The initial product can avoid subscriber email lists, raw subscriber records, and bulk message sending. It can keep analytics locally, refresh only while the app is running or when requested, and provide a disconnect and data-deletion control. A supported route may require reducing the feature set if some fields or actions are unavailable.

## Decision after a response

Map each approved field and action to the current dashboard and MCP tools. Ship only the supported subset for general users; keep the session-based prototype private until a distribution route is resolved. Record any permitted refresh schedule and retention limits before enabling background sync.
