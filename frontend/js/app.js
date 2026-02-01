/**
 * RuCaptioner Main Application
 * Initializes modules and handles view navigation
 */

const App = {
    currentView: 'folders',
    connectionCheckInterval: null,
    settingsModal: null,

    /**
     * Initialize the application
     */
    async init() {
        console.log('RuCaptioner initializing...');

        // Initialize modules
        Folders.init();
        Datasets.init();
        Jobs.init();
        Exports.init();

        // Initialize settings modal
        this.initSettingsModal();

        // Setup global modal cleanup handler
        this.setupModalCleanup();

        // Bind navigation
        this.bindNavigation();

        // Check connection
        await this.checkConnection();
        this.startConnectionCheck();

        // Load initial data
        await this.loadInitialData();

        // Check URL params for initial view
        const params = Utils.getQueryParams();
        if (params.view) {
            this.showView(params.view);
        }

        console.log('RuCaptioner ready');
    },

    /**
     * Setup global modal cleanup to prevent stuck backdrops
     */
    setupModalCleanup() {
        // Clean up backdrops whenever a modal is about to be shown
        document.addEventListener('show.bs.modal', () => {
            // Small delay to let Bootstrap create its backdrop first
            setTimeout(() => {
                // Remove any duplicate backdrops (should only be one)
                const backdrops = document.querySelectorAll('.modal-backdrop');
                if (backdrops.length > 1) {
                    for (let i = 1; i < backdrops.length; i++) {
                        backdrops[i].remove();
                    }
                }
            }, 50);
        });

        // Ensure cleanup when modal is hidden
        document.addEventListener('hidden.bs.modal', () => {
            // If no modals are open, ensure body classes are cleaned up
            const openModals = document.querySelectorAll('.modal.show');
            if (openModals.length === 0) {
                Utils.cleanupModalBackdrops();
            }
        });
    },

    /**
     * Initialize the settings modal
     */
    initSettingsModal() {
        const modalEl = document.getElementById('settingsModal');
        if (modalEl) {
            this.settingsModal = new bootstrap.Modal(modalEl);
        } else {
            console.error('Settings modal element not found');
        }

        // Settings button
        const settingsBtn = document.getElementById('settingsBtn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', (e) => {
                e.preventDefault();
                App.showSettings();
            });
        } else {
            console.error('Settings button not found');
        }

        // Trash button
        const trashBtn = document.getElementById('trashBtn');
        if (trashBtn) {
            trashBtn.addEventListener('click', (e) => {
                e.preventDefault();
                Folders.openTrashModal();
            });
        }

        // Save settings button
        document.getElementById('saveSettingsBtn')?.addEventListener('click', () => {
            App.saveSettings();
        });

        // Test connection buttons


        document.getElementById('testLmstudioBtn')?.addEventListener('click', () => {
            App.testConnection('lmstudio');
        });
    },

    /**
     * Show settings modal and load current config
     */
    async showSettings() {
        try {
            const config = await API.getConfig();
            this.populateSettingsForm(config);
            this.settingsModal.show();
        } catch (error) {
            Utils.showToast(i18n.t('settings_load_failed') + ': ' + error.message, 'danger');
        }
    },

    /**
     * Populate settings form with config values
     */
    populateSettingsForm(config) {
        // Vision settings
        // document.getElementById('settings_vision_backend').value = config.vision?.backend || 'lmstudio';
        document.getElementById('settings_vision_model').value = config.vision?.default_model || 'qwen2.5-vl-7b';
        // document.getElementById('settings_ollama_url').value = config.vision?.ollama_url || 'http://localhost:11434';
        document.getElementById('settings_lmstudio_url').value = config.vision?.lmstudio_url || 'http://localhost:1234';
        document.getElementById('settings_vision_max_tokens').value = config.vision?.max_tokens || 4096;
        document.getElementById('settings_vision_timeout').value = config.vision?.timeout_seconds || 120;
        document.getElementById('settings_vision_retries').value = config.vision?.max_retries || 2;

        // Thumbnail settings
        document.getElementById('settings_thumb_size').value = config.thumbnails?.max_size || 256;
        document.getElementById('settings_thumb_quality').value = config.thumbnails?.quality || 85;
        document.getElementById('settings_thumb_format').value = config.thumbnails?.format || 'webp';

        // Export settings
        document.getElementById('settings_export_format').value = config.export?.default_format || 'jpeg';
        document.getElementById('settings_export_quality').value = config.export?.default_quality || 95;
        document.getElementById('settings_export_padding').value = config.export?.default_padding || 6;

        // Debug
        document.getElementById('settings_debug').checked = config.server?.debug || false;

        // Trash
        document.getElementById('settings_trash_size').value = localStorage.getItem('cf_trash_limit') || 100;
    },

    /**
     * Collect form data and save settings
     */
    async saveSettings() {
        const config = {
            vision: {
                default_model: document.getElementById('settings_vision_model').value,
                lmstudio_url: document.getElementById('settings_lmstudio_url').value,
                max_tokens: parseInt(document.getElementById('settings_vision_max_tokens').value) || 4096,
                timeout_seconds: parseInt(document.getElementById('settings_vision_timeout').value) || 120,
                max_retries: parseInt(document.getElementById('settings_vision_retries').value) || 2,
            },
            thumbnails: {
                max_size: parseInt(document.getElementById('settings_thumb_size').value) || 256,
                quality: parseInt(document.getElementById('settings_thumb_quality').value) || 85,
                format: document.getElementById('settings_thumb_format').value,
            },
            export: {
                default_format: document.getElementById('settings_export_format').value,
                default_quality: parseInt(document.getElementById('settings_export_quality').value) || 95,
                default_padding: parseInt(document.getElementById('settings_export_padding').value) || 6,
            },
            server: {
                debug: document.getElementById('settings_debug').checked,
            }
        };

        // Save Trash Settings (LocalStorage)
        const trashLimit = parseInt(document.getElementById('settings_trash_size').value) || 100;
        localStorage.setItem('cf_trash_limit', trashLimit);
        Folders.trashLimit = trashLimit;

        try {
            const saveBtn = document.getElementById('saveSettingsBtn');
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving...';

            const result = await API.saveConfig(config);
            Utils.showToast(result.message || i18n.t('settings_saved_success'), 'success');
            this.settingsModal.hide();

        } catch (error) {
            Utils.showToast(i18n.t('settings_save_failed') + ': ' + error.message, 'danger');
        } finally {
            const saveBtn = document.getElementById('saveSettingsBtn');
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Settings';
        }
    },

    /**
     * Test connection to a backend
     */
    async testConnection(backend) {
        const btn = document.getElementById('testLmstudioBtn');
        const originalHtml = btn.innerHTML;

        try {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            const result = await API.testBackendConnection(backend);

            if (result.status === 'ok') {
                btn.innerHTML = '<i class="bi bi-check-lg text-success"></i>';
                Utils.showToast(result.message, 'success');
            } else {
                btn.innerHTML = '<i class="bi bi-x-lg text-danger"></i>';
                Utils.showToast(result.message, 'warning');
            }

            // Reset button after 2 seconds
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }, 2000);

        } catch (error) {
            btn.innerHTML = '<i class="bi bi-x-lg text-danger"></i>';
            Utils.showToast(i18n.t('connection_test_failed') + ': ' + error.message, 'danger');

            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }, 2000);
        }
    },

    /**
     * Bind navigation events
     */
    bindNavigation() {
        document.querySelectorAll('[data-view]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.showView(link.dataset.view);
            });
        });
    },

    /**
     * Show a specific view
     */
    showView(viewName) {
        // Update nav links
        document.querySelectorAll('[data-view]').forEach(link => {
            link.classList.toggle('active', link.dataset.view === viewName);
        });

        // Show/hide view containers
        document.querySelectorAll('.view-container').forEach(container => {
            container.style.display = container.id === `view-${viewName}` ? 'block' : 'none';
        });

        this.currentView = viewName;
        Utils.setQueryParam('view', viewName);

        // Load view-specific data
        this.onViewChange(viewName);
    },

    /**
     * View-aware fullscreen toggle proxy
     */
    toggleFullscreen() {
        if (this.currentView === 'folders' && window.Folders) {
            window.Folders.toggleFullscreen();
        } else if (this.currentView === 'datasets' && window.Datasets) {
            window.Datasets.toggleFullscreen();
        }
    },

    /**
     * Handle view change - load relevant data
     */
    async onViewChange(viewName) {
        switch (viewName) {
            case 'folders':
                await Folders.loadFolders();
                break;
            case 'datasets':
                await Datasets.loadDatasets();
                // If dataset images need refresh (files were added from folders)
                if (Datasets.needsRefresh && Datasets.currentDatasetId) {
                    // Refresh the current dataset's images AND stats
                    await Promise.all([
                        Datasets.loadDatasetDetails(Datasets.currentDatasetId),
                        Datasets.loadDatasetImages(Datasets.currentDatasetId, 1, true)
                    ]);
                    Datasets.needsRefresh = false;
                    Datasets.lastModifiedDatasetId = null;
                }
                break;
            case 'jobs':
                await Jobs.loadJobs();
                break;
            case 'exports':
                await Exports.loadExports();
                break;
        }
    },

    /**
     * Load initial data for the default view
     */
    async loadInitialData() {
        try {
            await Folders.loadFolders();
        } catch (error) {
            console.error('Failed to load initial data:', error);
        }
    },

    /**
     * Check connection to the backend
     */
    async checkConnection() {
        const statusEl = document.getElementById('connectionStatus');

        try {
            const health = await API.healthCheck();

            if (health.status === 'healthy') {
                statusEl.innerHTML = `<i class="bi bi-circle-fill text-success"></i> ${i18n.t('nav_status_connected')}`;
                statusEl.title = `LM Studio: ${health.lmstudio_available ? '✓' : '✗'}`;
            } else {
                statusEl.innerHTML = `<i class="bi bi-circle-fill text-warning"></i> ${i18n.t('status_unhealthy')}`;
                statusEl.title = i18n.t('status_db_issue');
            }
        } catch (error) {
            statusEl.innerHTML = `<i class="bi bi-circle-fill text-danger"></i> ${i18n.t('nav_status_disconnected')}`;
            statusEl.title = i18n.t('status_server_unreachable');
        }
    },

    /**
     * Start periodic connection check
     */
    startConnectionCheck() {
        this.connectionCheckInterval = setInterval(() => {
            this.checkConnection();
        }, 30000); // Check every 30 seconds
    },

    /**
     * Stop connection check
     */
    stopConnectionCheck() {
        if (this.connectionCheckInterval) {
            clearInterval(this.connectionCheckInterval);
            this.connectionCheckInterval = null;
        }
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    App.init();

    // Global keyboard manager for prioritised hotkeys
    window.addEventListener('keydown', (e) => {
        // Refined typing check: allow hotkeys on checkboxes/radios/buttons
        const tag = e.target.tagName;
        const isDetails = e.target.isContentEditable;
        const isInput = tag === 'INPUT' || tag === 'TEXTAREA';
        // Only block if it's a text-like input
        const isTyping = isDetails || (isInput && !['checkbox', 'radio', 'button', 'submit', 'reset', 'file'].includes(e.target.type));

        // If a blocking confirmation dialog is open, let it handle the input (specifically Enter/Escape)
        const confirmModal = document.getElementById('confirmModal');
        const isConfirmOpen = confirmModal && (confirmModal.classList.contains('show') || confirmModal.style.display === 'block' || document.body.classList.contains('confirm-active'));
        if (isConfirmOpen) return;

        // Undo/Redo (Ctrl+Z / Ctrl+Y)
        const isCtrl = e.ctrlKey || e.metaKey;
        if (isCtrl && !isTyping) {
            // Use e.code for layout independence (works with Russian 'я'/'н')
            if (e.code === 'KeyZ') {
                e.preventDefault();
                if (window.Folders && window.Folders.undoDelete) window.Folders.undoDelete();
                return;
            }
            if (e.code === 'KeyY') {
                e.preventDefault();
                if (window.Folders && window.Folders.redoDelete) window.Folders.redoDelete();
                return;
            }
        }

        const foldersModal = document.getElementById("imageDetailModal");
        const datasetsModal = document.getElementById("datasetCaptionModal");
        const fullscreenOverlay = document.getElementById("fullscreenOverlay");

        const isFoldersModalOpen = foldersModal && foldersModal.classList.contains("show");
        const isDatasetsModalOpen = datasetsModal && datasetsModal.classList.contains("show");
        const isFullscreenActive = fullscreenOverlay && !fullscreenOverlay.classList.contains("d-none");

        // 1. Deletion (Highest Priority, only if a modal or fullscreen is active)
        if (e.key === 'Delete') {
            // CRITICAL: Double check it is NOT the F key (just in case of weird mapping)
            if (e.code === 'KeyF' || e.key === 'f' || e.key === 'F') return;

            // DEBUG: Trace execution
            if (e.key === 'Delete') {
                console.warn("[App] Delete Key Detected. Calling deleteSelectedFiles...");
            }

            if (isFoldersModalOpen || isDatasetsModalOpen || isFullscreenActive || App.currentView === 'folders') {
                if (isTyping) return; // Let browser handle text editing

                e.preventDefault();
                e.stopImmediatePropagation(); // Don't let other listeners catch this

                // Handle Folders View
                if (App.currentView === 'folders') {
                    if (isFoldersModalOpen || (isFullscreenActive && App.currentView === 'folders')) {
                        // Detail View Delete
                        if (window.Folders && window.Folders.currentDetailFileId) {
                            window.Folders.deleteSingleFile(window.Folders.currentDetailFileId);
                        }
                    } else {
                        // Thumbnail View Delete (Bulk)
                        console.warn("DEBUG: Checking deleteSelectedFiles...", typeof window.Folders?.deleteSelectedFiles);
                        if (window.Folders && typeof window.Folders.deleteSelectedFiles === 'function') {
                            window.Folders.deleteSelectedFiles();
                        } else {
                            console.error("CRITICAL ERROR: window.Folders.deleteSelectedFiles is NOT a function!");
                        }
                    }
                }
                // Handle Datasets View
                else if (isDatasetsModalOpen || (isFullscreenActive && App.currentView === 'datasets')) {
                    if (window.Datasets && typeof window.Datasets.handleKeyboardDelete === 'function') {
                        window.Datasets.handleKeyboardDelete();
                    }
                }
                return;
            }
        }

        // 2. Navigation and Fullscreen (only if not typing)
        if (!isTyping) {
            const isNavKey = e.key === 'ArrowLeft' || e.key === 'ArrowRight';
            const isFullscreenKey = e.code === 'KeyF';
            const isEscape = e.key === 'Escape';

            if (isNavKey || isFullscreenKey || isEscape) {
                // If in Folders modal/fullscreen
                if (isFoldersModalOpen || (isFullscreenActive && App.currentView === 'folders')) {
                    if (isNavKey) {
                        e.preventDefault();
                        if (e.key === 'ArrowLeft') window.Folders.navigatePrev();
                        else window.Folders.navigateNext();
                    } else if (isFullscreenKey) {
                        e.preventDefault();
                        window.Folders.toggleFullscreen();
                    } else if (isEscape && isFullscreenActive) {
                        e.preventDefault();
                        window.Folders.toggleFullscreen();
                    }
                    if (isNavKey || isFullscreenKey || (isEscape && isFullscreenActive)) {
                        e.stopImmediatePropagation();
                        return;
                    }
                }

                // If in Datasets modal/fullscreen
                if (isDatasetsModalOpen || (isFullscreenActive && App.currentView === 'datasets')) {
                    if (isNavKey) {
                        e.preventDefault();
                        if (e.key === 'ArrowLeft') window.Datasets.navigatePrev();
                        else window.Datasets.navigateNext();
                    } else if (isFullscreenKey) {
                        e.preventDefault();
                        window.Datasets.toggleFullscreen();
                    } else if (isEscape && isFullscreenActive) {
                        e.preventDefault();
                        window.Datasets.toggleFullscreen();
                    }
                    if (isNavKey || isFullscreenKey || (isEscape && isFullscreenActive)) {
                        e.stopImmediatePropagation();
                        return;
                    }
                }

                // Global Escape for any open fullscreen (fallback)
                if (isEscape && isFullscreenActive) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    if (App.currentView === 'folders') window.Folders.toggleFullscreen();
                    else window.Datasets.toggleFullscreen();
                    return;
                }
            }
        }
    }, true);
});

// Make available globally
window.App = App;