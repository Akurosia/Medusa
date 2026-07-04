# coding=utf-8
"""Request handler for series operations."""
from __future__ import unicode_literals

import logging

from medusa import app, notifiers, ui
from medusa.helper.exceptions import CantRefreshShowException, ShowDirectoryNotFoundException
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.server.api.v2.series import SeriesHandler
from medusa.tv.episode import EpisodeNumber
from medusa.tv.series import Series, SeriesIdentifier
from medusa.helper.common import try_int

from requests.compat import quote_plus

from tornado.escape import json_decode

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


def _get_rename_roots(series, season=None):
    """Return one root episode per media file for rename operations."""
    ep_obj_rename_list = []
    for ep_obj in series.get_all_episodes(has_location=True, season=season):
        if not ep_obj.location:
            continue

        has_already = False
        for check in ep_obj.related_episodes + [ep_obj]:
            if check in ep_obj_rename_list:
                has_already = True
                break

        if not has_already:
            ep_obj_rename_list.append(ep_obj)

    return ep_obj_rename_list


class SeriesOperationHandler(BaseRequestHandler):
    """Operation request handler for series."""

    #: parent resource handler
    parent_handler = SeriesHandler
    #: resource name
    name = 'operation'
    #: identifier
    identifier = None
    #: path param
    path_param = None
    #: allowed HTTP methods
    allowed_methods = ('POST', )

    def post(self, series_slug):
        """Query series information.

        :param series_slug: series slug. E.g.: tvdb1234
        """
        series_identifier = SeriesIdentifier.from_slug(series_slug)
        if not series_identifier:
            return self._bad_request('Invalid series slug')

        series = Series.find_by_identifier(series_identifier)
        if not series:
            return self._not_found('Series not found')

        data = json_decode(self.request.body)
        if not data or not all([data.get('type')]):
            return self._bad_request('Invalid request body')

        if data['type'] == 'ARCHIVE_EPISODES':
            if series.set_all_episodes_archived(final_status_only=True):
                return self._created()
            return self._no_content()

        if data['type'] == 'REFRESH':
            season = try_int(data.get('season'), None)
            seasons = [season] if season is not None else None
            try:
                app.show_queue_scheduler.action.refreshShow(series, seasons=seasons)
            except CantRefreshShowException as error:
                return self._bad_request(str(error))

            return self._created()

        if data['type'] == 'RENAME_SEASON':
            season = try_int(data.get('season'), None)
            if season is None:
                return self._bad_request('You must provide a season')

            app.show_queue_scheduler.action.renameShowEpisodes(series, seasons=[season])
            return self._created()

        if data['type'] == 'TEST_RENAME':
            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                return self._bad_request("Can't rename episodes when the show dir is missing.")

            filter_season = data.get('season')

            ep_obj_rename_list = _get_rename_roots(series, season=filter_season)
            if ep_obj_rename_list:
                ep_obj_rename_list.reverse()
            return self._ok(data=[
                {**ep_obj.to_json(detailed=True), **{'selected': False}} for ep_obj in ep_obj_rename_list
            ])

        if data['type'] == 'RENAME_EPISODES':
            episodes = data.get('episodes', [])
            if not episodes:
                return self._bad_request('You must provide at least one episode')

            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                return self._bad_request("Can't rename episodes when the show dir is missing.")

            selected_episodes = set()
            for episode_slug in episodes:
                episode_number = EpisodeNumber.from_slug(episode_slug)
                if not episode_number:
                    continue

                selected_episodes.add((episode_number.season, episode_number.episode))

            for root_ep_obj in _get_rename_roots(series):
                related_numbers = {
                    (ep_obj.season, ep_obj.episode)
                    for ep_obj in root_ep_obj.related_episodes + [root_ep_obj]
                }
                if not selected_episodes.intersection(related_numbers):
                    continue

                root_ep_obj.rename()
            return self._created()

        # This might also be moved to /notifications/kodi/update?showslug=..
        if data['type'] == 'UPDATE_KODI':
            series_name = quote_plus(series.name.encode('utf-8'))

            if app.KODI_UPDATE_ONLYFIRST:
                host = app.KODI_HOST[0].strip()
            else:
                host = ', '.join(app.KODI_HOST)

            if notifiers.kodi_notifier.update_library(series_name=series_name):
                ui.notifications.message(f'Library update command sent to KODI host(s): {host}')
            else:
                ui.notifications.error(f'Unable to contact one or more KODI host(s): {host}')

            return self._created()

        return self._bad_request('Invalid operation')
