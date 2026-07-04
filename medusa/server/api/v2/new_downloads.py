# coding=utf-8
"""Request handler for recent downloaded episode maintenance."""
from __future__ import unicode_literals

import datetime
import logging
from collections import OrderedDict
from datetime import date

from tornado.escape import json_decode

from medusa import app, db
from medusa.common import DOWNLOADED, SNATCHED, SNATCHED_BEST, SNATCHED_PROPER, statusStrings
from medusa.helper.common import try_int
from medusa.helper.exceptions import CantRefreshShowException, ShowDirectoryNotFoundException
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.server.api.v2.series_operation import _get_rename_roots
from medusa.show.history import History
from medusa.tv.episode import EpisodeNumber
from medusa.tv.series import Series, SeriesIdentifier


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


def _recent_download_cutoff(days):
    """Return a history-table cutoff string for the requested day window."""
    days = max(try_int(days, 14), 1)
    return (datetime.datetime.today() - datetime.timedelta(days=days)).strftime(History.date_format)


def _recent_airdate_cutoff(days):
    """Return an episode airdate cutoff ordinal for the requested day window."""
    days = max(try_int(days, 14), 1)
    return (date.today() - datetime.timedelta(days=days)).toordinal()


def _history_date_from_airdate(airdate):
    """Convert an episode airdate ordinal to a sortable history-like date string."""
    try:
        episode_date = date.fromordinal(int(airdate))
    except (TypeError, ValueError):
        return ''

    if episode_date <= date.fromordinal(1):
        return ''

    return episode_date.strftime('%Y%m%d000000')


def _series_from_slug(series_slug):
    """Return a loaded series object from a slug."""
    series_identifier = SeriesIdentifier.from_slug(series_slug)
    if not series_identifier:
        return None

    return Series.find_by_identifier(series_identifier)


def _normalize_items(items):
    """Return operation items with integer season lists."""
    normalized = []
    for item in items or []:
        series_slug = item.get('showSlug') or item.get('series')
        seasons = sorted({
            season
            for season in [try_int(season, None) for season in item.get('seasons', [])]
            if season is not None
        })
        episodes = {
            (
                try_int(episode.get('season'), None),
                try_int(episode.get('episode'), None)
            )
            for episode in item.get('episodes', [])
        }
        episodes = {
            episode
            for episode in episodes
            if episode[0] is not None and episode[1] is not None
        }
        if series_slug and seasons:
            normalized.append({'showSlug': series_slug, 'seasons': seasons, 'episodes': episodes})
    return normalized


class NewDownloadsHandler(BaseRequestHandler):
    """Recent downloaded episode maintenance request handler."""

    #: resource name
    name = 'new-downloads'
    #: identifier
    identifier = None
    #: path param
    path_param = None
    #: allowed HTTP methods
    allowed_methods = ('GET', 'POST')

    def get(self):
        """Return shows and seasons with recent snatched/downloaded episodes."""
        days = try_int(self.get_argument('days', default=14), 14)
        history_cutoff = _recent_download_cutoff(days)
        airdate_cutoff = _recent_airdate_cutoff(days)
        interesting_statuses = (SNATCHED, SNATCHED_PROPER, SNATCHED_BEST, DOWNLOADED)
        status_placeholders = ','.join('?' * len(interesting_statuses))

        main_db_con = db.DBConnection()
        history_rows = main_db_con.select(
            """
            SELECT h.indexer_id, h.showid, h.season,
                   h.episode,
                   h.action AS status,
                   MAX(h.date) AS latest_date
            FROM history h
            JOIN tv_episodes e
              ON e.indexer = h.indexer_id
             AND e.showid = h.showid
             AND e.season = h.season
             AND e.episode = h.episode
            WHERE h.action IN ({status_placeholders})
              AND h.date >= ?
            GROUP BY h.indexer_id, h.showid, h.season, h.episode
            ORDER BY latest_date DESC
            """.format(status_placeholders=status_placeholders),
            list(interesting_statuses) + [history_cutoff]
        )
        current_rows = main_db_con.select(
            """
            SELECT e.indexer AS indexer_id, e.showid, e.season,
                   e.episode, e.status, e.airdate
            FROM tv_episodes e
            WHERE e.status IN ({status_placeholders})
              AND e.airdate >= ?
              AND e.airdate <= ?
            ORDER BY e.airdate DESC
            """.format(status_placeholders=status_placeholders),
            list(interesting_statuses) + [airdate_cutoff, date.today().toordinal()]
        )

        grouped = OrderedDict()
        seen = set()

        def add_episode_row(row, latest_date):
            row_key = (row['indexer_id'], row['showid'], row['season'], row['episode'])
            if row_key in seen:
                return
            seen.add(row_key)

            identifier = SeriesIdentifier.from_id(row['indexer_id'], row['showid'])
            series = Series.find_by_identifier(identifier)
            if not series:
                return

            group = grouped.setdefault(identifier.slug, {
                'showSlug': identifier.slug,
                'title': series.title,
                'location': series.location,
                'seasons': [],
                'episodeCount': 0,
                'latestDate': latest_date,
                'selected': True
            })
            season_group = next((season for season in group['seasons'] if season['season'] == row['season']), None)
            if not season_group:
                season_group = {
                    'season': row['season'],
                    'episodeCount': 0,
                    'episodes': [],
                    'latestDate': latest_date
                }
                group['seasons'].append(season_group)

            season_group['episodes'].append({
                'season': row['season'],
                'episode': row['episode'],
                'status': row['status'],
                'statusName': statusStrings.get(row['status'], 'Unknown'),
                'latestDate': latest_date
            })
            season_group['episodeCount'] += 1
            group['episodeCount'] += 1
            if latest_date > season_group['latestDate']:
                season_group['latestDate'] = latest_date
            if latest_date > group['latestDate']:
                group['latestDate'] = latest_date

        for row in history_rows:
            add_episode_row(row, row['latest_date'])

        for row in current_rows:
            add_episode_row(row, _history_date_from_airdate(row['airdate']))

        return self._ok(data=list(grouped.values()))

    def post(self):
        """Run a recent-download maintenance operation."""
        data = json_decode(self.request.body)
        if not data or not data.get('type'):
            return self._bad_request('Invalid request body')

        if data['type'] == 'REFRESH':
            return self._refresh_items(_normalize_items(data.get('items', [])))

        if data['type'] == 'TEST_RENAME':
            return self._test_rename(_normalize_items(data.get('items', [])))

        if data['type'] == 'RENAME_EPISODES':
            return self._rename_episodes(data.get('episodes', []))

        return self._bad_request('Invalid operation')

    def _refresh_items(self, items):
        """Queue season-limited refreshes for selected items."""
        queued = []
        errors = []
        for item in items:
            series = _series_from_slug(item['showSlug'])
            if not series:
                errors.append({'showSlug': item['showSlug'], 'error': 'Series not found'})
                continue

            try:
                app.show_queue_scheduler.action.refreshShow(series, seasons=item['seasons'])
                queued.append(item)
            except CantRefreshShowException as error:
                errors.append({'showSlug': item['showSlug'], 'error': str(error)})

        return self._accepted(data={'queued': queued, 'errors': errors})

    def _test_rename(self, items):
        """Return rename previews across selected shows and seasons."""
        rename_rows = []
        errors = []
        for item in items:
            series = _series_from_slug(item['showSlug'])
            if not series:
                errors.append({'showSlug': item['showSlug'], 'error': 'Series not found'})
                continue

            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                errors.append({'showSlug': item['showSlug'], 'error': "Can't rename episodes when the show dir is missing."})
                continue

            selected_episodes = item['episodes']
            for ep_obj in _get_rename_roots(series, season=item['seasons']):
                if selected_episodes:
                    related_numbers = {
                        (related_ep.season, related_ep.episode)
                        for related_ep in ep_obj.related_episodes + [ep_obj]
                    }
                    if not selected_episodes.intersection(related_numbers):
                        continue

                rename_rows.append({
                    **ep_obj.to_json(detailed=True),
                    **{
                        'showSlug': item['showSlug'],
                        'showTitle': series.title,
                        'showLocation': series.location,
                        'selected': False
                    }
                })

        rename_rows.reverse()
        return self._ok(data={'episodes': rename_rows, 'errors': errors})

    def _rename_episodes(self, episodes):
        """Rename selected episode roots grouped by show."""
        if not episodes:
            return self._bad_request('You must provide at least one episode')

        selected_by_show = {}
        for episode in episodes:
            series_slug = episode.get('showSlug')
            episode_number = EpisodeNumber.from_slug(episode.get('slug'))
            if not series_slug or not episode_number:
                continue

            selected_by_show.setdefault(series_slug, set()).add((episode_number.season, episode_number.episode))

        renamed = 0
        errors = []
        for series_slug, selected_episodes in selected_by_show.items():
            series = _series_from_slug(series_slug)
            if not series:
                errors.append({'showSlug': series_slug, 'error': 'Series not found'})
                continue

            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                errors.append({'showSlug': series_slug, 'error': "Can't rename episodes when the show dir is missing."})
                continue

            for root_ep_obj in _get_rename_roots(series):
                related_numbers = {
                    (ep_obj.season, ep_obj.episode)
                    for ep_obj in root_ep_obj.related_episodes + [root_ep_obj]
                }
                if not selected_episodes.intersection(related_numbers):
                    continue

                root_ep_obj.rename()
                renamed += 1

        return self._created(data={'renamed': renamed, 'errors': errors})
