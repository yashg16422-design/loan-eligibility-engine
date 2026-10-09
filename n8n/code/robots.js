/**
 * robots.txt rules for the crawler (RFC 9309), pure functions.
 *
 * - Our crawler identifies as "LoanEligibilityEngine"; we obey the group for that token,
 *   else the "*" group.
 * - Longest matching rule wins; on a tie, Allow wins. `*` and `$` wildcards supported.
 * - robots.txt status: 200 -> parse; 401/403 -> treat as "disallow all" (conservative:
 *   the site is refusing bots); other 4xx -> no rules (RFC 9309: allowed);
 *   5xx / unreachable -> "disallow all" (RFC 9309: assume complete disallow).
 */

const CRAWLER_TOKEN = 'loaneligibilityengine';

/** Parse robots.txt into groups: [{ agents: [..], rules: [{ allow, pattern }] }]. */
function parseRobots(text) {
  const groups = [];
  let current = null;
  let lastWasAgent = false;
  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.replace(/#.*$/, '').trim();
    const m = /^([A-Za-z-]+)\s*:\s*(.*)$/.exec(line);
    if (!m) continue;
    const field = m[1].toLowerCase();
    const value = m[2].trim();
    if (field === 'user-agent') {
      if (!current || !lastWasAgent) { current = { agents: [], rules: [] }; groups.push(current); }
      current.agents.push(value.toLowerCase());
      lastWasAgent = true;
    } else if ((field === 'allow' || field === 'disallow') && current) {
      lastWasAgent = false;
      if (value) current.rules.push({ allow: field === 'allow', pattern: value });
    } else {
      lastWasAgent = false;
    }
  }
  return groups;
}

/** Rules of the group that applies to us (our token, else "*"). */
function rulesFor(groups, token = CRAWLER_TOKEN) {
  const own = groups.filter((g) => g.agents.some((a) => a !== '*' && token.includes(a)));
  const chosen = own.length ? own : groups.filter((g) => g.agents.includes('*'));
  return chosen.flatMap((g) => g.rules);
}

function patternToRegex(pattern) {
  const anchored = pattern.endsWith('$');
  const body = (anchored ? pattern.slice(0, -1) : pattern)
    .split('*')
    .map((part) => part.replace(/[.+?^${}()|[\]\\]/g, '\\$&'))
    .join('.*');
  return new RegExp(`^${body}${anchored ? '$' : ''}`);
}

/**
 * Path + query of an absolute URL, without the `URL` global: n8n 2.x runs Code nodes
 * in a sandbox where `URL` is not defined.
 */
function pathOf(url) {
  const m = /^https?:\/\/[^/?#]+([^#]*)/i.exec(String(url));
  const rest = m ? m[1] : '';
  return rest.startsWith('/') ? rest : `/${rest}`;
}

/** Is `url` allowed, given the robots.txt fetch result for its origin? */
function isAllowed(url, robots) {
  const status = robots ? Number(robots.status) : 0;
  if (status === 401 || status === 403) return false;
  if (status >= 400 && status < 500) return true;
  if (status !== 200) return false;
  const path = pathOf(url);
  let best = null;
  for (const rule of rulesFor(parseRobots(robots.body))) {
    if (!patternToRegex(rule.pattern).test(path)) continue;
    const len = rule.pattern.replace(/\*|\$$/g, '').length;
    if (!best || len > best.len || (len === best.len && rule.allow)) best = { len, allow: rule.allow };
  }
  return best ? best.allow : true;
}

if (typeof module !== 'undefined') module.exports = { parseRobots, rulesFor, isAllowed, pathOf, CRAWLER_TOKEN };
