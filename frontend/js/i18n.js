class I18nManager {
    constructor() {
        // Load language preference from local storage or default to 'ru' (since we rebranded to RuCaptioner)
        this.lang = localStorage.getItem('app_language') || 'ru';
        this.translations = typeof TRANSLATIONS !== 'undefined' ? TRANSLATIONS : {};

        // Bind methods
        this.t = this.t.bind(this);
        this.setLanguage = this.setLanguage.bind(this);
        this.updatePage = this.updatePage.bind(this);
    }

    /**
     * Get translated string for a key
     * @param {string} key - Translation key
     * @returns {string} Translated string or original key
     */
    t(key) {
        if (!this.translations[key]) {
            console.warn(`[I18n] Missing translation for key: ${key}`);
            return key;
        }
        return this.translations[key][this.lang] || this.translations[key]['en'] || key;
    }

    /**
     * Set active language
     * @param {string} lang - Language code ('en' or 'ru')
     */
    setLanguage(lang) {
        if (lang !== 'en' && lang !== 'ru') return;

        this.lang = lang;
        localStorage.setItem('app_language', lang);

        // Update HTML lang attribute
        document.documentElement.lang = lang;

        // Update all elements on the page
        this.updatePage();

        // Trigger event for other components to react
        window.dispatchEvent(new CustomEvent('languageChanged', { detail: { language: lang } }));

        console.log(`[I18n] Language set to: ${lang}`);
    }

    /**
     * Toggle between EN and RU
     */
    toggleLanguage() {
        const newLang = this.lang === 'ru' ? 'en' : 'ru';
        this.setLanguage(newLang);
        return newLang;
    }

    /**
     * Update all DOM elements with data-i18n attribute
     */
    updatePage() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translated = this.t(key);

            // Handle inputs with placeholders vs text content
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (el.hasAttribute('placeholder')) {
                    el.placeholder = translated;
                }
            } else {
                // Determine if we should replace text content or specific child
                // Ideally, we replace textContent, but if there are icons, we need to be careful.
                // Simple approach: if element has children (like icons), we try to find a text node or specific span.
                // Assuming well-structure HTML where text is wrapped or data-i18n is on the text span.

                // If the element has specific structure (icon + text), formatting might be tricky.
                // Best practice: put data-i18n ONLY on the text node container.
                el.textContent = translated;
            }
        });

        // Update elements with placeholder localization
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            el.placeholder = this.t(key);
        });

        // Update elements with title localization (tooltips)
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.title = this.t(key);
        });

        // Update Toggle Button UI
        const toggleBtn = document.getElementById('langToggleBtn');
        if (toggleBtn) {
            const flag = this.lang === 'ru' ? '🇷🇺' : '🇺🇸';
            const text = this.lang === 'ru' ? 'RU' : 'EN';
            toggleBtn.innerHTML = `${flag} ${text}`;
        }
    }

    /**
     * Initialize i18n
     */
    init() {
        this.updatePage();
    }
}

// Create global instance
const i18n = new I18nManager();

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    i18n.init();
});
