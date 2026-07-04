<template>
    <div id="manage-new-downloads" class="align-left">
        <div class="header-with-buttons">
            <h1 class="header">New Downloads</h1>
            <div class="buttons">
                <label class="days-filter">
                    Last
                    <input v-model.number="days" type="number" min="1" max="365" class="form-control input-sm">
                    days
                </label>
                <button class="btn-medusa btn-inline" :disabled="loading" @click="loadDownloads">Reload</button>
                <button class="btn-medusa btn-inline" :disabled="!selectedItems.length || refreshing || loading" @click="refreshSelected">
                    Refresh for new episode<span v-if="selectedItems.length"> ({{selectedItems.length}})</span>
                </button>
                <button class="btn-medusa btn-inline btn-success" :disabled="!selectedItems.length || refreshing || previewLoading" @click="loadRenamePreview">
                    Rename new episodes
                </button>
            </div>
        </div>

        <state-switch v-if="loading" state="loading" class="loading" />

        <table class="defaultTable" cellspacing="1" border="0" cellpadding="0">
            <thead>
                <tr class="seasoncols">
                    <th class="col-checkbox"><input type="checkbox" :checked="allSelected" @change="checkAll($event.currentTarget.checked)"></th>
                    <th>Show</th>
                    <th>Seasons</th>
                    <th class="nowrap">Episodes</th>
                    <th class="nowrap">Latest download</th>
                </tr>
            </thead>
            <tbody>
                <tr v-if="!loading && downloads.length === 0" class="seasonstyle">
                    <td colspan="5">No recent downloaded episodes found.</td>
                </tr>
                <tr v-for="show in downloads" :key="show.showSlug" class="seasonstyle">
                    <td class="col-checkbox"><input v-model="show.selected" type="checkbox"></td>
                    <td><app-link :href="`home/displayShow?showslug=${show.showSlug}`">{{show.title}}</app-link></td>
                    <td>{{formatSeasons(show.seasons)}}</td>
                    <td class="nowrap">{{show.episodeCount}}</td>
                    <td class="nowrap">{{formatHistoryDate(show.latestDate)}}</td>
                </tr>
            </tbody>
        </table>

        <div v-if="refreshing" class="refresh-status">
            <state-switch state="loading" />
            Waiting for queued season refreshes to finish... ({{refreshProgress.done}}/{{refreshProgress.total}})
        </div>

        <div v-if="errors.length" class="alert alert-warning">
            <div v-for="error in errors" :key="`${error.showSlug}-${error.error}`">
                {{error.showSlug}}: {{error.error}}
            </div>
        </div>

        <div v-if="previewLoaded" class="rename-preview">
            <h3>Preview of the proposed name changes</h3>
            <div class="rename-cancel">
                <button class="btn-medusa btn-success" :disabled="!selectedRenameEpisodes.length || previewLoading" @click="renameSelected">
                    Rename Selected<span v-if="selectedRenameEpisodes.length"> ({{selectedRenameEpisodes.length}})</span>
                </button>
                <button type="button" class="btn-medusa btn-xs selectAllShows" @click="checkRename(true)">Select all</button>
                <button type="button" class="btn-medusa btn-xs unselectAllShows" @click="checkRename(false)">Clear all</button>
            </div>

            <state-switch v-if="previewLoading" state="loading" class="loading" />

            <table v-for="showGroup in renameGroups" :key="showGroup.showSlug" class="defaultTable" cellspacing="1" border="0" cellpadding="0">
                <thead>
                    <tr class="seasonheader">
                        <td colspan="5">
                            <span class="season-header">{{showGroup.showTitle}}</span>
                        </td>
                    </tr>
                </thead>
                <tbody>
                    <template v-for="season in showGroup.seasons">
                        <tr :key="`${showGroup.showSlug}-${season.season}-header`" class="seasonheader">
                            <td colspan="5">
                                <span class="season-header sub">{{season.season === 0 ? 'Specials' : `Season ${season.season}`}}</span>
                            </td>
                        </tr>
                        <tr :key="`${showGroup.showSlug}-${season.season}-cols`" class="seasoncols">
                            <th class="col-checkbox">
                                <input :disabled="season.episodes.filter(episode => episode.naming.result).length === 0" type="checkbox" @click="checkRename($event.currentTarget.checked, showGroup.showSlug, season.season)">
                            </th>
                            <th class="nowrap">Episode</th>
                            <th class="col-name">Old Location</th>
                            <th class="col-name">New Location</th>
                            <th class="nowrap">Result</th>
                        </tr>
                        <tr v-for="episode in season.episodes" :key="`${episode.showSlug}-${episode.slug}`" :class="[episode.naming.result ? 'wanted' : 'good']" class="seasonstyle">
                            <td class="col-checkbox">
                                <input :disabled="!episode.naming.result" v-model="episode.selected" type="checkbox" class="epCheck">
                            </td>
                            <td align="center" valign="top" class="nowrap">{{formatRelated(episode)}}</td>
                            <td width="38%" class="col-name">{{episode.naming.currentLocation}}</td>
                            <td width="38%" class="col-name">{{episode.naming.newLocation}}</td>
                            <td class="nowrap">{{episode.naming.result ? 'Rename' : 'No change'}}</td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>
    </div>
</template>

<script>
import { mapState } from 'vuex';
import { AppLink, StateSwitch } from './helpers';

export default {
    name: 'manage-new-downloads',
    components: {
        AppLink,
        StateSwitch
    },
    data() {
        return {
            days: 14,
            downloads: [],
            renameEpisodes: [],
            errors: [],
            loading: false,
            refreshing: false,
            previewLoading: false,
            previewLoaded: false,
            refreshItems: [],
            refreshDone: 0,
            pollTimer: null
        };
    },
    computed: {
        ...mapState({
            client: state => state.auth.client
        }),
        selectedItems() {
            return this.downloads
                .filter(show => show.selected)
                .map(show => ({
                    showSlug: show.showSlug,
                    seasons: show.seasons.map(season => season.season),
                    episodes: show.seasons.reduce((episodes, season) => episodes.concat(season.episodes), [])
                }));
        },
        allSelected() {
            return this.downloads.length > 0 && this.downloads.every(show => show.selected);
        },
        selectedRenameEpisodes() {
            return this.renameEpisodes.filter(episode => episode.selected && episode.naming.result);
        },
        refreshProgress() {
            return {
                done: this.refreshDone,
                total: this.refreshItems.length
            };
        },
        renameGroups() {
            const grouped = [];
            for (const episode of this.renameEpisodes) {
                let showGroup = grouped.find(show => show.showSlug === episode.showSlug);
                if (!showGroup) {
                    showGroup = { showSlug: episode.showSlug, showTitle: episode.showTitle, seasons: [] };
                    grouped.push(showGroup);
                }

                let seasonGroup = showGroup.seasons.find(season => season.season === episode.season);
                if (!seasonGroup) {
                    seasonGroup = { season: episode.season, episodes: [] };
                    showGroup.seasons.push(seasonGroup);
                }

                seasonGroup.episodes.push(episode);
            }

            return grouped;
        }
    },
    mounted() {
        this.loadDownloads();
    },
    beforeDestroy() {
        this.clearPollTimer();
    },
    methods: {
        async loadDownloads() {
            try {
                this.loading = true;
                this.previewLoaded = false;
                this.renameEpisodes = [];
                this.errors = [];
                const { data } = await this.client.api.get('new-downloads', {
                    params: { days: this.days },
                    timeout: 120000
                });
                this.downloads = data;
            } catch (error) {
                this.$snotify.error('Error while loading recent downloads', 'Error');
            } finally {
                this.loading = false;
            }
        },
        async refreshSelected() {
            try {
                this.refreshing = true;
                this.previewLoaded = false;
                this.renameEpisodes = [];
                this.errors = [];
                this.refreshDone = 0;
                this.refreshItems = this.selectedItems;
                const { data } = await this.client.api.post('new-downloads', {
                    type: 'REFRESH',
                    items: this.refreshItems
                }, { timeout: 120000 });
                this.errors = data.errors || [];
                this.refreshItems = data.queued || [];
                this.$snotify.info(`Queued season refresh for ${data.queued.length} show(s)`, 'Refresh queued');
                await this.waitForRefresh(this.refreshItems);
                this.$snotify.success('Season refresh finished for selected new downloads', 'Refresh complete');
            } catch (error) {
                this.$snotify.error('Error while queueing the season refresh', 'Error');
            } finally {
                this.refreshing = false;
                this.refreshItems = [];
                this.refreshDone = 0;
            }
        },
        waitForRefresh(items) {
            return new Promise(resolve => {
                if (items.length === 0) {
                    resolve();
                    return;
                }

                const poll = async () => {
                    const activeCount = await this.getActiveRefreshWorkCount(items);
                    this.refreshDone = items.length - activeCount;
                    if (activeCount === 0) {
                        this.clearPollTimer();
                        resolve();
                        return;
                    }

                    this.pollTimer = window.setTimeout(poll, 5000);
                };

                this.pollTimer = window.setTimeout(poll, 1500);
            });
        },
        async getActiveRefreshWorkCount(items) {
            const activeActions = ['isBeingUpdated', 'isBeingRefreshed', 'isInRefreshQueue', 'isInUpdateQueue'];
            let activeCount = 0;
            for (const item of items) {
                try {
                    const { data } = await this.client.api.get(`series/${item.showSlug}`, {
                        params: { detailed: true, numbering: false },
                        timeout: 60000
                    });
                    if (data.showQueueStatus && data.showQueueStatus.some(status => activeActions.includes(status.action) && status.active)) {
                        activeCount += 1;
                    }
                } catch (error) {
                    activeCount += 1;
                }
            }

            return activeCount;
        },
        clearPollTimer() {
            if (this.pollTimer) {
                window.clearTimeout(this.pollTimer);
                this.pollTimer = null;
            }
        },
        async loadRenamePreview() {
            try {
                this.previewLoading = true;
                this.previewLoaded = true;
                const { data } = await this.client.api.post('new-downloads', {
                    type: 'TEST_RENAME',
                    items: this.selectedItems
                }, { timeout: 600000 });
                this.errors = data.errors || [];
                this.renameEpisodes = data.episodes.map(episode => ({
                    ...episode,
                    naming: this.namingChanged(episode)
                }));
                if (this.renameEpisodes.length === 0) {
                    this.$snotify.info('No rename candidates found. Snatched episodes will appear here after a local file is available.', 'Rename preview');
                }
            } catch (error) {
                this.$snotify.error('Error while loading the rename preview', 'Error');
            } finally {
                this.previewLoading = false;
            }
        },
        async renameSelected() {
            try {
                this.previewLoading = true;
                const { data } = await this.client.api.post('new-downloads', {
                    type: 'RENAME_EPISODES',
                    episodes: this.selectedRenameEpisodes.map(episode => ({
                        showSlug: episode.showSlug,
                        slug: episode.slug
                    }))
                }, { timeout: 600000 });
                this.errors = data.errors || [];
                this.$snotify.success(`Renamed ${data.renamed} episode file(s)`, 'Rename complete');
                await this.loadRenamePreview();
            } catch (error) {
                this.$snotify.error('Error while trying to perform the rename task', 'Error');
            } finally {
                this.previewLoading = false;
            }
        },
        namingChanged(episode) {
            const location = episode.file && episode.file.location ? episode.file.location : '';
            const showLocation = episode.showLocation || '';
            const currentLocation = showLocation && location.indexOf(showLocation) === 0 ?
                location.slice(showLocation.length + 1) :
                location;
            const parts = currentLocation.split('.');
            const currentLocationExt = parts.length > 1 ? parts[parts.length - 1] : '';
            const newLocation = currentLocationExt ?
                `${episode.file.properPath}.${currentLocationExt}` :
                episode.file.properPath;

            return {
                result: Boolean(currentLocation) && currentLocation !== newLocation,
                currentLocation,
                newLocation
            };
        },
        formatSeasons(seasons) {
            return seasons.map(season => season.season === 0 ? 'Specials' : `Season ${season.season}`).join(', ');
        },
        formatHistoryDate(value) {
            if (!value || value.length !== 14) {
                return value || '';
            }

            return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)} ${value.slice(8, 10)}:${value.slice(10, 12)}`;
        },
        formatRelated(episode) {
            const relatedEpisodes = [episode, ...episode.related];
            if (relatedEpisodes.length === 1) {
                return relatedEpisodes[0].episode;
            }

            const first = relatedEpisodes[0];
            const last = relatedEpisodes[relatedEpisodes.length - 1];
            return `${first.episode}-${last.episode}`;
        },
        checkAll(value) {
            for (const show of this.downloads) {
                show.selected = value;
            }
        },
        checkRename(value, showSlug = null, season = null) {
            for (const episode of this.renameEpisodes) {
                if (!episode.naming.result) {
                    continue;
                }
                if ((showSlug === null || episode.showSlug === showSlug) && (season === null || episode.season === season)) {
                    episode.selected = value;
                }
            }
        }
    }
};
</script>

<style scoped>
.header-with-buttons {
    align-items: center;
}

.buttons {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
}

.days-filter {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin: 0;
    font-weight: 400;
}

.days-filter input {
    width: 70px;
}

.loading,
.refresh-status {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 10px 0;
}

.defaultTable {
    margin: 0.3em 0 1em;
}

.defaultTable tr.seasonheader > td {
    padding: 0;
}

.season-header {
    color: white;
    font-family: inherit;
    font-weight: 700;
    line-height: 1.1;
    background-color: rgb(51, 51, 51);
    display: block;
    padding: 5px;
    font-size: 1em;
}

.season-header.sub {
    background-color: rgb(68, 68, 68);
    font-size: 0.95em;
}

.rename-cancel {
    margin: 5px 0;
}
</style>
