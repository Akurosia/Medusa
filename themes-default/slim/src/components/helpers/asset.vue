<template>
    <div v-if="!lazy" style="display: inherit">
        <img v-if="!link" v-bind="{ src, class: cls, class: newCls }" @error="markMissing">
        <app-link v-else :href="href">
            <img v-bind="{ src, class: newCls, style: imgStyle }" @error="markMissing">
        </app-link>
    </div>
    <div v-else style="display: inherit">
        <lazy-image v-if="!link" :lazy-src="src" :lazy-cls="newCls" :lazy-default-src="defaultSrc" :lazy-width="imgWidth" />
        <app-link v-else :href="href">
            <lazy-image :lazy-src="src" :lazy-cls="newCls" :lazy-default-src="defaultSrc" />
        </app-link>
    </div>
</template>
<script>
import { mapState } from 'vuex';
import AppLink from './app-link.vue';
import LazyImage from './lazy-image.vue';

export default {
    name: 'asset',
    components: {
        AppLink,
        LazyImage
    },
    props: {
        showSlug: String,
        type: {
            type: String,
            required: true
        },
        defaultSrc: {
            type: String,
            required: true
        },
        link: {
            type: Boolean,
            default: false
        },
        cls: String,
        imgWidth: Number,
        lazy: Boolean,
        imgStyle: String
    },
    data() {
        return {
            error: false
        };
    },
    computed: {
        ...mapState({
            apiKey: state => state.auth.apiKey
        }),
        src() {
            const { apiKey, defaultSrc, error, showSlug, type } = this;

            if (error || !showSlug || !type || this.isMarkedMissing()) {
                return defaultSrc;
            }

            return `api/v2/series/${showSlug}/asset/${type}?api_key=${apiKey}`;
        },
        href() {
            const { link, src } = this;
            // Compute a link to the full asset, if applicable
            if (link) {
                return src.replace('Thumb', '');
            }
            return undefined;
        },
        newCls() {
            const { cls, imgWidth } = this;
            let newClass = cls;

            if (imgWidth) {
                newClass += ` width-${imgWidth}`;
            }

            return newClass;
        },
        newStyle() {
            const { imgWidth, imgStyle } = this;
            let tempStyle = '';
            if (imgStyle) {
                tempStyle = imgStyle;
            }

            if (imgWidth) {
                tempStyle += `;width=${imgWidth}px`;
            }
            return tempStyle;
        }
    },
    methods: {
        missingAssetKey() {
            const { showSlug, type } = this;
            return showSlug && type ? `missing-asset:${showSlug}:${type}` : null;
        },
        isMarkedMissing() {
            const key = this.missingAssetKey();
            return key && window.sessionStorage.getItem(key) === '1';
        },
        markMissing() {
            const key = this.missingAssetKey();
            if (key) {
                window.sessionStorage.setItem(key, '1');
            }
            this.error = true;
        }
    }
};
</script>
<style scoped>
.width-40 {
    width: 40px;
}

.width-50 {
    width: 50px;
}

</style>
