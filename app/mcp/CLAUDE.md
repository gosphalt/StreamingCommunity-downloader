# MCP server

- **An MCP tool that changes anything calls the route handler, never the layer beneath it.** The agent acts as the
  token's owner, with their live permissions (`auth.token_owner()`), passed to the handler as
  `request.state.user` exactly as `AuthMiddleware` would set it; the tool checks the permission
  the route's dependency declares, since dependencies do not run on a direct call. The first
  version reimplemented follow, season batches and requests beside the routers and lost, in
  turn: the seed-or-roll-back (an unreadable source left a watch armed with no baseline, so the
  next cycle queued the back catalogue), `downloads_notify.abandon()` (a season that failed
  mid-submit never closed its batch), and the requester (it filed requests as the first Jellyfin
  admin). The token itself fails closed — no stored hash means no access — travels only in the
  `Authorization` header (a query string lands in proxy logs), and is not a second server:
  `/mcp` is a route of the panel, in `PUBLIC_PATHS` only because it authenticates itself.
