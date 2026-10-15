#!/usr/bin/env bash
# The radar page's live loop (Radar workflow, job "Live loop"): every 5 minutes bring
# the live frames up to date (`mvd radar-live`) and force-push them as a single commit to
# the branch radar-live; after LOOP_MINUTES start the next loop (workflow_dispatch of
# this workflow, which waits in the concurrency group until this one has ended).
#
# Environment: GH_TOKEN (contents: write, actions: write), GITHUB_REPOSITORY,
# GITHUB_REF_NAME; optional LOOP_MINUTES (default 340), EVERY_MINUTES (5),
# OFFSET_SECONDS (60: ČHMÚ publishes a composite within a minute after its time),
# HOURS (24), SATELLITE_HOURS (24), HANDOVER (1: dispatch the next loop; 0: do not).
# See docs/data-sources.md#live-loop.
set -uo pipefail

LOOP_MINUTES=${LOOP_MINUTES:-340}
EVERY=${EVERY_SECONDS:-$(( ${EVERY_MINUTES:-5} * 60 ))}
OFFSET=${OFFSET_SECONDS:-60}
HOURS=${HOURS:-24}
SATELLITE_HOURS=${SATELLITE_HOURS:-24}
HANDOVER=${HANDOVER:-1}
remote="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
start=$(date +%s)
end=$(( start + LOOP_MINUTES * 60 ))

# the published folder as a git repository holding the current commit of radar-live, so
# a push sends only the new files
if git ls-remote --exit-code --heads "$remote" radar-live >/dev/null 2>&1; then
  git clone --quiet --depth 1 --branch radar-live --single-branch "$remote" live
else
  echo "no radar-live branch yet; starting empty"
  git init --quiet -b radar-live live
  git -C live remote add origin "$remote"
fi
git -C live config user.name "github-actions[bot]"
git -C live config user.email "41898282+github-actions[bot]@users.noreply.github.com"
mkdir -p cache

publish() {
  (
    cd live || exit 1
    git checkout --quiet --orphan next
    git add -A
    git commit --quiet -m "radar: live frames $(date -u +%Y-%m-%dT%H:%MZ)" || exit 0
    git branch --quiet -M radar-live
    git push --quiet --force origin radar-live
  )
}

handed_over=0
round=0
while :; do
  round=$(( round + 1 ))
  t0=$(date +%s)
  if uv run --frozen mvd radar-live --dir live --cache cache --hours "$HOURS" \
      --satellite-hours "$SATELLITE_HOURS"; then
    if publish; then
      echo "round $round published after $(( $(date +%s) - t0 )) s ($(du -sh --exclude=.git live | cut -f1))"
    else
      echo "::warning::round $round: push to radar-live failed"
    fi
  else
    echo "::warning::round $round: update failed; trying again in the next round"
  fi
  now=$(date +%s)
  # start the next loop a few minutes early: it waits until this one has ended
  if [ "$HANDOVER" = 1 ] && [ $handed_over = 0 ] && [ $(( end - now )) -lt $(( EVERY + 120 )) ]; then
    if gh workflow run radar.yml --repo "$GITHUB_REPOSITORY" --ref "${GITHUB_REF_NAME:-main}" \
        -f live=true -f handover=true; then
      echo "dispatched the next live loop"
    else
      echo "::warning::could not dispatch the next loop; the hourly schedule will start one"
    fi
    handed_over=1
  fi
  next=$(( now / EVERY * EVERY + OFFSET ))
  [ "$next" -le "$now" ] && next=$(( next + EVERY ))
  if [ "$next" -ge "$end" ]; then
    break
  fi
  sleep $(( next - now ))
done
echo "live loop done after $round rounds"
