/**
 * RuCaptioner Folders Module
 * Handles folder browsing and file selection with drag-and-drop support
 */

const Folders = {
    currentFolderId: null,
    currentPage: 1,
    pageSize: 50,
    selectedFiles: new Set(),
    files: [],
    totalFiles: 0,
    isLoading: false,
    hasMoreFiles: true,
    currentFilter: 'all',
    allFilesSelected: false,  // Track if "select all" was clicked
    lastSelectedFileId: null, // Anchor for range selection (Shift+Click)
    currentDetailFileId: null, // ID of file currently shown in details modal

    // Trash Bin State
    trashBin: [],
    trashLimit: 100,

    /**
     * Check if running in Electron desktop mode
     */
    isDesktopMode() {
        return typeof window.electronAPI !== 'undefined' && window.electronAPI.isElectron;
    },

    /**
     * Initialize the folders module
     */
    init() {
        this.loadTrash();
        this.bindEvents();
        this.initDragAndDrop();
    },

    /**
     * Initialize drag-and-drop support
     */
    initDragAndDrop() {
        // Prevent default drag behaviors on the whole document
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.body.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        // Handle global drop - check if it's over the sidebar or main area
        document.body.addEventListener('drop', async (e) => {
            Utils.log('info', 'folders', 'Global drop event triggered', { isDesktopMode: this.isDesktopMode() });

            const files = e.dataTransfer.files;
            const items = e.dataTransfer.items;

            // In Electron, we can get the full path directly from dropped files!
            if (this.isDesktopMode() && files.length > 0 && files[0].path) {
                const droppedPath = files[0].path;
                Utils.log('info', 'folders', `Electron: got dropped path: ${droppedPath}`);

                // Check if it's a directory using the webkitGetAsEntry API
                let isDirectory = false;
                if (items && items.length > 0) {
                    const entry = items[0].webkitGetAsEntry?.();
                    isDirectory = entry?.isDirectory || false;
                }

                if (!isDirectory) {
                    // If they dropped a file, get its parent directory
                    const folderPath = droppedPath.replace(/[/\\][^/\\]+$/, '');
                    Utils.log('info', 'folders', `Dropped file, using parent: ${folderPath}`);
                    this.showAddFolderModalWithPath(folderPath);
                } else {
                    this.showAddFolderModalWithPath(droppedPath);
                }
                return;
            }

            // Fallback: try to get folder name from webkitGetAsEntry
            let folderName = null;
            if (items) {
                for (let i = 0; i < items.length; i++) {
                    const item = items[i].webkitGetAsEntry?.();
                    if (item && item.isDirectory) {
                        folderName = item.name;
                        break;
                    }
                }
            }

            // Browser fallback - guide user to paste path
            if (folderName) {
                Utils.log('info', 'folders', `Dropped folder detected (no path): ${folderName}`);
                this.showAddFolderModal(folderName);
            } else {
                // If it's just files, maybe they want to add to dataset?
                // For now, if no folder is detected, show warning or ignore
                Utils.showToast('Please drop a folder to track it', 'info');
            }
        }, false);
    },

    /**
     * Show add folder modal with path pre-filled (for Electron drag-drop)
     */
    showAddFolderModalWithPath(folderPath) {
        const modal = new bootstrap.Modal(document.getElementById('addFolderModal'));
        const pathInput = document.getElementById('folderPath');
        const nameInput = document.getElementById('folderName');

        pathInput.value = folderPath;
        nameInput.value = folderPath.split(/[/\\]/).pop();

        modal.show();
        Utils.showToast('Folder path captured!', 'success');
    },

    /**
     * Show the add folder modal with optional pre-filled name
     */
    showAddFolderModal(folderName = '') {
        const modal = new bootstrap.Modal(document.getElementById('addFolderModal'));
        const pathInput = document.getElementById('folderPath');
        const nameInput = document.getElementById('folderName');

        pathInput.value = '';
        nameInput.value = folderName;
        pathInput.placeholder = 'C:\\path\\to\\images';

        modal.show();

        if (folderName) {
            // Focus path input and try to auto-paste from clipboard
            document.getElementById('addFolderModal').addEventListener('shown.bs.modal', async () => {
                pathInput.focus();
                try {
                    const clipText = await navigator.clipboard.readText();
                    if (clipText && clipText.includes(folderName) && (clipText.includes('\\') || clipText.includes('/'))) {
                        pathInput.value = clipText.replace(/^["']|["']$/g, '');
                        Utils.showToast('Path auto-filled from clipboard!', 'success');
                    }
                } catch (err) {
                    // Clipboard access denied - that's fine
                }
            }, { once: true });
        }
    },

    /**
     * Browse for folder using native dialog (Electron) or show modal (browser)
     */
    async browseForFolder() {
        Utils.log('info', 'folders', 'browseForFolder() called', { isDesktopMode: this.isDesktopMode() });

        if (this.isDesktopMode()) {
            // Use Electron's native folder dialog
            try {
                Utils.log('debug', 'folders', 'Calling electronAPI.selectFolder()');
                const folderPath = await window.electronAPI.selectFolder('Select Image Folder');
                Utils.log('info', 'folders', `Native folder picker result: ${folderPath}`);

                if (folderPath) {
                    // We got a real path! Fill in the modal and show it
                    const modal = new bootstrap.Modal(document.getElementById('addFolderModal'));
                    document.getElementById('folderPath').value = folderPath;
                    document.getElementById('folderName').value = folderPath.split(/[/\\]/).pop();
                    modal.show();
                }
            } catch (err) {
                Utils.log('error', 'folders', `Folder picker error: ${err.message}`, { error: err });
                Utils.showToast('Error opening folder picker', 'error');
            }
        } else {
            // Browser fallback - just show the modal
            Utils.log('debug', 'folders', 'Browser mode: showing manual path modal');
            this.showAddFolderModal();
        }
    },

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Add folder button - use native browse in desktop mode
        document.getElementById('addFolderBtn').addEventListener('click', () => {
            if (this.isDesktopMode()) {
                // In desktop mode, go straight to folder picker
                this.browseForFolder();
            } else {
                // Browser mode - show modal with manual path entry
                const modal = new bootstrap.Modal(document.getElementById('addFolderModal'));
                document.getElementById('folderPath').placeholder = 'C:\\path\\to\\images';
                modal.show();
            }
        });

        // Browse path button inside modal
        document.getElementById('browsePathBtn')?.addEventListener('click', async () => {
            if (this.isDesktopMode()) {
                try {
                    const folderPath = await window.electronAPI.selectFolder('Select Image Folder');
                    if (folderPath) {
                        document.getElementById('folderPath').value = folderPath;
                        document.getElementById('folderName').value = folderPath.split(/[/\\]/).pop();
                    }
                } catch (err) {
                    console.error('Folder picker error:', err);
                    Utils.showToast('Error opening folder picker', 'error');
                }
            } else {
                Utils.showToast('Native folder browsing is only available in desktop mode. Please paste the path manually.', 'info');
            }
        });

        // Confirm add folder
        document.getElementById('confirmAddFolder').addEventListener('click', () => this.addFolder());

        // Confirm edit folder
        document.getElementById('confirmEditFolder')?.addEventListener('click', () => this.saveEditFolder());

        // Paste path button
        document.getElementById('pastePathBtn')?.addEventListener('click', async () => {
            try {
                const clipText = await navigator.clipboard.readText();
                if (clipText) {
                    // Remove surrounding quotes if present (Windows "Copy as path" adds them)
                    document.getElementById('folderPath').value = clipText.replace(/^["']|["']$/g, '');
                }
            } catch (err) {
                Utils.showToast('Unable to access clipboard. Please paste manually (Ctrl+V)', 'warning');
            }
        });

        // Select all button
        document.getElementById('selectAllBtn').addEventListener('click', () => this.toggleSelectAll());

        // Add to dataset button
        document.getElementById('addToDatasetBtn').addEventListener('click', () => this.showAddToDatasetDialog());

        // Delete selected button
        document.getElementById('deleteSelectedBtn')?.addEventListener('click', () => this.deleteSelectedFiles());

        // Confirm add to dataset button (in modal)
        document.getElementById('confirmAddToDataset')?.addEventListener('click', () => this.confirmAddToDataset());

        // Dataset mode toggle (select existing vs create new)
        document.getElementById('modeSelectExisting')?.addEventListener('change', () => {
            document.getElementById('selectExistingSection').style.display = 'block';
            document.getElementById('createNewSection').style.display = 'none';
            document.getElementById('confirmAddButtonText').textContent = 'Add Files';
        });

        document.getElementById('modeCreateNew')?.addEventListener('change', () => {
            document.getElementById('selectExistingSection').style.display = 'none';
            document.getElementById('createNewSection').style.display = 'block';
            document.getElementById('confirmAddButtonText').textContent = 'Create & Add';
        });

        // File filter
        document.getElementById('fileFilterType').addEventListener('change', (e) => {
            if (this.currentFolderId) {
                this.loadFolderFiles(this.currentFolderId, 1, e.target.value, true);
            }
        });

        // Thumbnail size slider
        document.getElementById('thumbnailSize').addEventListener('input', (e) => {
            Utils.setThumbnailSize(e.target.value);
        });

        // Image detail modal - save caption button
        document.getElementById('saveImageCaption')?.addEventListener('click', () => this.saveImageCaption());

        // Image detail modal - generate caption button
        document.getElementById('generateImageCaption')?.addEventListener('click', () => this.generateSingleCaption());

        // Image detail modal - delete button
        document.getElementById('imageDetailDeleteBtn')?.addEventListener('click', () => {
            console.log('[Folders] Delete button clicked for file:', this.currentDetailFileId);
            if (this.currentDetailFileId) {
                this.deleteSingleFile(this.currentDetailFileId);
            }
        });

        // Caption character counter
        const captionEl = document.getElementById('imageDetailCaption');
        const charCountEl = document.getElementById('captionCharCount');
        if (captionEl && charCountEl) {
            captionEl.addEventListener('input', () => {
                const len = captionEl.value.length;
                charCountEl.textContent = `${len} character${len === 1 ? '' : 's'}`;
            });
        }

        // Keyboard navigation

        // Deselect on grid background click
        document.getElementById('imageGrid').addEventListener('click', (e) => {
            // Check if click is directly on the grid or an element that is NOT an image card
            if (e.target.id === 'imageGrid' || e.target.id === 'loadMoreIndicator' || e.target.closest('#loadMoreIndicator')) {
                // Deselect all
                if (this.selectedFiles.size > 0) {
                    this.selectedFiles.clear();
                    this.allFilesSelected = false;
                    this.lastSelectedFileId = null;

                    document.querySelectorAll('#imageGrid .image-card').forEach(card => {
                        card.classList.remove('selected');
                        const checkbox = card.querySelector('.select-checkbox');
                        if (checkbox) checkbox.checked = false;
                    });

                    this.updateSelectionUI();
                }
            }
        });

        // Trash Bin Events
        document.getElementById('trashRestoreAllBtn')?.addEventListener('click', () => {
            if (confirm('Restore all files from trash?')) {
                const allIds = this.trashBin.map(t => t.id);
                this.restoreTrashItems(allIds);
            }
        });

        document.getElementById('trashEmptyBtn')?.addEventListener('click', () => this.emptyTrash());

        document.getElementById('trashSelectAllBtn')?.addEventListener('click', () => {
            document.querySelectorAll('.trash-selector').forEach(cb => cb.checked = true);
            this.updateTrashButtons();
        });

        document.getElementById('trashDeselectAllBtn')?.addEventListener('click', () => {
            document.querySelectorAll('.trash-selector').forEach(cb => cb.checked = false);
            this.updateTrashButtons();
        });

        document.getElementById('trashRestoreSelectedBtn')?.addEventListener('click', () => {
            const ids = Array.from(document.querySelectorAll('.trash-selector:checked')).map(cb => cb.value);
            this.restoreTrashItems(ids);
        });

        document.getElementById('trashDeleteSelectedBtn')?.addEventListener('click', () => {
            const ids = Array.from(document.querySelectorAll('.trash-selector:checked')).map(cb => cb.value);
            this.deleteTrashItems(ids);
        });
    },

    /**
     * Navigate to previous image
     */
    navigatePrev() {
        if (!this.files || this.files.length === 0 || !this.currentDetailFileId) return;

        const currentIndex = this.files.findIndex(f => f.id === this.currentDetailFileId);
        if (currentIndex > 0) {
            const prevFile = this.files[currentIndex - 1];
            this.showImageDetails(prevFile.id);
        }
    },

    /**
     * Navigate to next image
     */
    navigateNext() {
        if (!this.files || this.files.length === 0 || !this.currentDetailFileId) return;

        const currentIndex = this.files.findIndex(f => f.id === this.currentDetailFileId);
        if (currentIndex !== -1 && currentIndex < this.files.length - 1) {
            const nextFile = this.files[currentIndex + 1];
            this.showImageDetails(nextFile.id);
        }
    },

    /**
     * Toggle fullscreen view
     */
    toggleFullscreen(imageSrc = null) {
        const overlay = document.getElementById('fullscreenOverlay');
        const img = document.getElementById('fullscreenImage');

        if (!overlay || !img) return;

        // Force reset focus to avoid any hidden buttons keeping focus and intercepting keys
        if (document.activeElement) {
            document.activeElement.blur();
        }
        overlay.focus(); // Focus the overlay itself if possible, or body

        if (overlay.classList.contains('d-none')) {
            // Open fullscreen
            if (imageSrc) {
                img.src = imageSrc;
            } else if (!img.src && this.currentDetailFileId) {
                img.src = API.getImageUrl(this.currentDetailFileId);
            }
            overlay.classList.remove('d-none');
            document.body.classList.add('fullscreen-active');
            overlay.focus();
        } else {
            // Close fullscreen
            overlay.classList.add('d-none');
            document.body.classList.remove('fullscreen-active');

            // Restore focus to the modal to ensure Esc key works for it
            const modalEl = document.getElementById('imageDetailModal');
            if (modalEl) modalEl.focus();
        }
    },

    /**
     * Load and display folders list
     */
    async loadFolders() {
        const list = document.getElementById('folderList');
        list.innerHTML = Utils.loadingSpinner('sm');

        try {
            const folders = await API.listFolders();

            if (folders.length === 0) {
                list.innerHTML = Utils.emptyState('bi-folder2-open', i18n.t('no_folders_tracked'), i18n.t('click_plus_to_add'));
                return;
            }

            list.innerHTML = folders.map(folder => `
                <a href="#" class="list-group-item list-group-item-action ${folder.id === this.currentFolderId ? 'active' : ''}" 
                   data-folder-id="${folder.id}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <i class="bi bi-folder me-2"></i>
                            <span>${Utils.escapeHtml(folder.name || folder.path.split(/[\\/]/).pop())}</span>
                        </div>
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-light btn-sm edit-btn" title="Edit">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-outline-light btn-sm rescan-btn" title="Rescan">
                                <i class="bi bi-arrow-clockwise"></i>
                            </button>
                            <button class="btn btn-outline-danger btn-sm remove-btn" title="Remove">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div class="folder-info mt-1">
                        <small>${folder.file_count} files • Last scan: ${Utils.formatRelativeTime(folder.last_scan)}</small>
                    </div>
                </a>
            `).join('');

            // Bind folder click events
            list.querySelectorAll('[data-folder-id]').forEach(el => {
                el.addEventListener('click', (e) => {
                    // Ignore if clicking buttons
                    if (e.target.closest('.btn')) return;
                    e.preventDefault();
                    this.selectFolder(el.dataset.folderId);
                });

                // Edit button
                el.querySelector('.edit-btn').addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.showEditFolderModal(el.dataset.folderId);
                });

                // Rescan button
                el.querySelector('.rescan-btn').addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.rescanFolder(el.dataset.folderId);
                });

                // Remove button
                el.querySelector('.remove-btn').addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.removeFolder(el.dataset.folderId);
                });
            });

        } catch (error) {
            list.innerHTML = Utils.emptyState('bi-exclamation-triangle', i18n.t('error_loading_folders'), error.message);
            Utils.showToast(i18n.t('error_loading_folders') + ': ' + error.message, 'error');
        }
    },

    /**
     * Add a new folder
     */
    async addFolder() {
        const path = document.getElementById('folderPath').value.trim();
        const name = document.getElementById('folderName').value.trim() || null;
        const recursive = document.getElementById('scanRecursively').checked;

        if (!path) {
            Utils.showToast(i18n.t('please_enter_folder_path'), 'warning');
            return;
        }

        const btn = document.getElementById('confirmAddFolder');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Adding...';

        try {
            const folder = await API.addFolder(path, name, recursive);
            Utils.showToast(`${i18n.t('added_folder')}: ${folder.name || path}`, 'success');

            // Close modal and refresh
            bootstrap.Modal.getInstance(document.getElementById('addFolderModal')).hide();
            document.getElementById('addFolderForm').reset();

            await this.loadFolders();
            this.selectFolder(folder.id);

        } catch (error) {
            let errorMsg = error.message;
            if (errorMsg.includes('Folder already tracked')) {
                errorMsg = i18n.t('error_folder_exists');
            } else {
                errorMsg = i18n.t('failed_add_folder') + ': ' + errorMsg;
            }
            Utils.showToast(errorMsg, 'error');
        } finally {
            btn.disabled = false;
            // Restore button with i18n span
            btn.innerHTML = `<i class="bi bi-plus-lg me-1"></i><span data-i18n="modal_add_folder_btn">${i18n.t('modal_add_folder_btn')}</span>`;
        }
    },

    /**
     * Select a folder and load its files
     */
    async selectFolder(folderId) {
        this.currentFolderId = folderId;
        this.selectedFiles.clear();
        this.allFilesSelected = false;
        this.lastSelectedFileId = null;
        this.currentPage = 1;
        this.hasMoreFiles = true;
        this.files = [];
        this.updateSelectionUI();

        // Update active state in list
        document.querySelectorAll('#folderList [data-folder-id]').forEach(el => {
            el.classList.toggle('active', el.dataset.folderId === folderId);
        });

        const filter = document.getElementById('fileFilterType').value;
        await this.loadFolderFiles(folderId, 1, filter, true);
    },

    /**
     * Load files for a folder with infinite scroll support
     */
    async loadFolderFiles(folderId, page = 1, filter = 'all', reset = false) {
        if (this.isLoading) return;

        const grid = document.getElementById('imageGrid');

        // Show initial loading spinner on first load
        if (reset) {
            grid.innerHTML = Utils.loadingSpinner();
            this.files = [];
            this.currentPage = 1;
            this.hasMoreFiles = true;
            this.currentFilter = filter;
        }

        this.isLoading = true;
        this.currentPage = page;

        try {
            const folder = await API.getFolder(folderId);
            const response = await API.getFolderFiles(folderId, page, this.pageSize, filter);

            this.totalFiles = response.total;

            // Update header
            document.getElementById('folderTitle').innerHTML = `<i class="bi bi-folder me-2"></i>${Utils.escapeHtml(folder.name || folder.path)}`;
            document.getElementById('fileCount').textContent = `${response.total} files`;

            // Enable toolbar buttons
            document.getElementById('selectAllBtn').disabled = false;

            if (response.files.length === 0 && reset) {
                grid.innerHTML = Utils.emptyState('bi-images', 'No images found', filter !== 'all' ? 'Try changing the filter' : '');
                this.hasMoreFiles = false;
                return;
            }

            // Append new files to the list
            this.files.push(...response.files);
            this.hasMoreFiles = this.files.length < response.total;

            // Render new image cards (append if not reset)
            const newCardsHtml = response.files.map(file => this.renderImageCard(file)).join('');

            if (reset) {
                grid.innerHTML = newCardsHtml;
            } else {
                grid.insertAdjacentHTML('beforeend', newCardsHtml);
            }

            // Bind click events to new cards only
            this.bindImageCardEvents();

            // Setup infinite scroll on first load
            if (reset) {
                this.setupInfiniteScroll(grid);
            }

            // Remove pagination, add loading indicator if more files available
            document.getElementById('imagePagination').style.display = 'none';

            // Manage loading indicator
            let indicator = document.getElementById('loadMoreIndicator');
            if (this.hasMoreFiles) {
                if (!indicator) {
                    indicator = document.createElement('div');
                    indicator.id = 'loadMoreIndicator';
                    indicator.className = 'text-center text-muted py-2';
                    indicator.innerHTML = '<small><i class="bi bi-arrow-down-circle"></i> Scroll for more...</small>';
                    // Insert at the end of the grid
                    grid.appendChild(indicator);
                }
            } else if (indicator) {
                indicator.remove();
            }

        } catch (error) {
            if (this.currentPage === 1) {
                grid.innerHTML = Utils.emptyState('bi-exclamation-triangle', 'Error loading files', error.message);
            }
            Utils.showToast('Failed to load files: ' + error.message, 'error');
        } finally {
            this.isLoading = false;
        }
    },

    setupInfiniteScroll(grid) {
        // Use the grid directly since it has overflow:auto and its own scrollbar
        if (!grid) return;

        // Remove any existing scroll listener
        if (this._scrollHandler) {
            grid.removeEventListener('scroll', this._scrollHandler);
        }

        this._scrollHandler = () => {
            if (this.isLoading || !this.hasMoreFiles || !this.currentFolderId) return;

            // Use grid for scroll positions since it has the scrollbar
            const scrollTop = grid.scrollTop;
            const scrollHeight = grid.scrollHeight;
            const clientHeight = grid.clientHeight;

            // Trigger when within 1000px of bottom
            if (scrollTop + clientHeight >= scrollHeight - 1000) {
                console.log('[Folders] Scroll threshold reached, loading page', this.currentPage + 1);
                this.loadFolderFiles(this.currentFolderId, this.currentPage + 1, this.currentFilter, false);
            }
        };

        grid.addEventListener('scroll', this._scrollHandler);

        // Initial check in case content doesn't fill the screen
        setTimeout(() => this._scrollHandler(), 600);
    },

    /**
     * Render an image card
     */
    renderImageCard(file) {
        const isSelected = this.selectedFiles.has(file.id);
        const qualityClass = Utils.getQualityClass(file.quality_score);

        return `
            <div class="image-card draggable ${isSelected ? 'selected' : ''}" data-file-id="${file.id}" draggable="true">
                <div class="checkbox-area">
                    <input type="checkbox" class="form-check-input select-checkbox" ${isSelected ? 'checked' : ''}>
                </div>
                <img src="${API.getThumbnailUrl(file.id)}" alt="${Utils.escapeHtml(file.filename)}" loading="lazy">
                ${file.has_caption ? '<span class="badge bg-success caption-badge"><i class="bi bi-chat-quote-fill"></i></span>' : ''}
                ${qualityClass ? `<span class="quality-indicator ${qualityClass}"></span>` : ''}
                <div class="image-overlay">
                    <span>${Utils.escapeHtml(Utils.truncate(file.filename, 25))}</span>
                </div>
            </div>
        `;
    },

    /**
     * Bind events to image cards
     */
    bindImageCardEvents() {
        document.querySelectorAll('#imageGrid .image-card').forEach(card => {
            const fileId = card.dataset.fileId;
            const checkboxArea = card.querySelector('.checkbox-area');
            const checkbox = checkboxArea.querySelector('input');

            // Card click - handle selection and details
            card.addEventListener('click', (e) => {
                // If the click originated from the checkbox area, ignore it here
                if (checkboxArea.contains(e.target)) return;

                // Check for modifier keys
                if (e.ctrlKey || e.metaKey) {
                    // Ctrl/Cmd + Click: Toggle selection
                    this.toggleFileSelection(fileId, card, checkbox);
                } else if (e.shiftKey) {
                    // Shift + Click: Range selection
                    e.preventDefault(); // Prevent text selection
                    this.selectRange(fileId);
                } else {
                    // Normal click: Show details and set as anchor
                    this.lastSelectedFileId = fileId;
                    this.showImageDetails(fileId);
                }
            });

            // Checkbox Area Events - Isolate from Card Dragging

            // 1. Prevent drag start on the checkbox area essential!
            checkboxArea.addEventListener('dragstart', (e) => {
                e.preventDefault();
                e.stopPropagation();
                return false;
            });

            // 2. Prevent mousedown propagation to card (which starts drag)
            checkboxArea.addEventListener('mousedown', (e) => {
                e.stopPropagation();
            });

            // 3. Handle click manually
            checkboxArea.addEventListener('click', (e) => {
                e.stopPropagation(); // Stop bubbling to card
                e.preventDefault(); // Prevent default checkbox toggle (we do it manually)

                this.toggleFileSelection(fileId, card, checkbox);
            });

            // Drag start - set up data for dropping into datasets
            card.addEventListener('dragstart', (e) => {
                card.classList.add('dragging');

                // If the dragged item is selected, drag all selected items
                // If not selected, just drag this one item
                let dragIds;
                if (this.selectedFiles.has(fileId)) {
                    dragIds = Array.from(this.selectedFiles);
                } else {
                    dragIds = [fileId];
                }

                // Set the drag data
                e.dataTransfer.setData('application/x-captionforge-images', JSON.stringify(dragIds));
                e.dataTransfer.setData('text/plain', `${dragIds.length} image(s)`);
                e.dataTransfer.effectAllowed = 'copy';

                // Create a custom drag image showing count
                if (dragIds.length > 1) {
                    const dragImage = document.createElement('div');
                    dragImage.className = 'drag-image-preview';
                    dragImage.innerHTML = `<i class="bi bi-images"></i> ${dragIds.length} images`;
                    dragImage.style.cssText = 'position:absolute;top:-1000px;padding:8px 12px;background:#CA8A04;color:#000;border-radius:4px;font-weight:500;';
                    document.body.appendChild(dragImage);
                    e.dataTransfer.setDragImage(dragImage, 0, 0);
                    setTimeout(() => dragImage.remove(), 0);
                }
            });

            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
            });
        });
    },

    /**
     * Toggle file selection
     */
    toggleFileSelection(fileId, card, checkbox) {
        // Set this file as the anchor for subsequent range selections
        this.lastSelectedFileId = fileId;

        if (this.selectedFiles.has(fileId)) {
            this.selectedFiles.delete(fileId);
            card.classList.remove('selected');
            checkbox.checked = false;
        } else {
            this.selectedFiles.add(fileId);
            card.classList.add('selected');
            checkbox.checked = true;
        }
        this.updateSelectionUI();
    },

    /**
     * Select a range of files (Shift+Click)
     */
    selectRange(targetFileId) {
        if (!this.lastSelectedFileId || !this.files || this.files.length === 0) {
            // No anchor, just select the target
            const card = document.querySelector(`.image-card[data-file-id="${targetFileId}"]`);
            const checkbox = card?.querySelector('.select-checkbox');
            if (card && checkbox) {
                this.toggleFileSelection(targetFileId, card, checkbox);
            }
            return;
        }

        const startIdx = this.files.findIndex(f => f.id === this.lastSelectedFileId);
        const endIdx = this.files.findIndex(f => f.id === targetFileId);

        if (startIdx === -1 || endIdx === -1) return;

        const start = Math.min(startIdx, endIdx);
        const end = Math.max(startIdx, endIdx);

        // Add all files in range to selection
        for (let i = start; i <= end; i++) {
            const file = this.files[i];
            this.selectedFiles.add(file.id);
        }

        // Update UI
        this.updateSelectionUI();
        document.querySelectorAll('#imageGrid .image-card').forEach(card => {
            if (this.selectedFiles.has(card.dataset.fileId)) {
                card.classList.add('selected');
                const cb = card.querySelector('.select-checkbox');
                if (cb) cb.checked = true;
            }
        });
    },

    /**
     * Toggle select all
     */
    async toggleSelectAll() {
        const isAllSelected = this.allFilesSelected || (this.selectedFiles.size === this.totalFiles);

        if (isAllSelected) {
            // Deselect all
            this.selectedFiles.clear();
            this.allFilesSelected = false;

            document.querySelectorAll('#imageGrid .image-card').forEach(card => {
                card.classList.remove('selected');
                const checkbox = card.querySelector('.select-checkbox');
                if (checkbox) checkbox.checked = false;
            });
        } else {
            // Select all - need to fetch all file IDs if we haven't loaded them all
            if (this.files.length < this.totalFiles) {
                try {
                    // Fetch all file IDs from the backend
                    const filter = this.currentFilter || 'all';
                    const response = await API.getFolderFiles(this.currentFolderId, 1, this.totalFiles, filter);

                    // Add all IDs to selection
                    this.selectedFiles.clear();
                    response.files.forEach(file => this.selectedFiles.add(file.id));
                    this.allFilesSelected = true;
                } catch (error) {
                    Utils.showToast('Failed to fetch all files: ' + error.message, 'error');
                    return;
                }
            } else {
                // All files are loaded, just select them
                this.files.forEach(file => this.selectedFiles.add(file.id));
            }

            // Update UI for currently visible cards
            document.querySelectorAll('#imageGrid .image-card').forEach(card => {
                card.classList.add('selected');
                const checkbox = card.querySelector('.select-checkbox');
                if (checkbox) checkbox.checked = true;
            });
        }

        this.updateSelectionUI();
    },

    /**
     * Update selection UI elements
     */
    updateSelectionUI() {
        const count = this.selectedFiles.size;

        // Add to Dataset Button
        const btn = document.getElementById('addToDatasetBtn');
        if (btn) {
            btn.disabled = count === 0;
            // Only update text to include count if selection > 0
            if (count > 0) {
                btn.innerHTML = `<i class="bi bi-plus-lg"></i> Datasets`;
            } else {
                btn.innerHTML = `<i class="bi bi-plus-lg"></i> Datasets`;
            }
        }

        // Delete Button
        const deleteBtn = document.getElementById('deleteSelectedBtn');
        if (deleteBtn) {
            deleteBtn.disabled = count === 0;
            // deleteBtn.innerHTML = `<i class="bi bi-trash"></i> Delete`; 
        }

        const selectBtn = document.getElementById('selectAllBtn');
        // Update select all button text
        const isAllSelected = this.allFilesSelected || (this.totalFiles > 0 && this.selectedFiles.size === this.totalFiles);
        selectBtn.innerHTML = isAllSelected
            ? `<i class="bi bi-x-lg"></i> ${i18n.t('folders_clear_selection')}`
            : `<i class="bi bi-check2-all"></i> ${i18n.t('folders_select_all')}${this.totalFiles > 0 ? ' (' + this.totalFiles + ')' : ''}`;
    },


    /**
     * Show add to dataset dialog
     */
    async showAddToDatasetDialog() {
        if (this.selectedFiles.size === 0) return;

        try {
            const datasets = await API.listDatasets();

            // Reset modal to "Select Existing" mode
            document.getElementById('modeSelectExisting').checked = true;
            document.getElementById('selectExistingSection').style.display = 'block';
            document.getElementById('createNewSection').style.display = 'none';
            document.getElementById('confirmAddButtonText').textContent = 'Add Files';
            document.getElementById('newDatasetName').value = '';
            document.getElementById('newDatasetDescription').value = '';

            // Populate the dataset selector
            const select = document.getElementById('selectDatasetList');
            if (datasets.length === 0) {
                select.innerHTML = '<option value="">No datasets available</option>';
                // Auto-switch to create new mode
                document.getElementById('modeCreateNew').checked = true;
                document.getElementById('selectExistingSection').style.display = 'none';
                document.getElementById('createNewSection').style.display = 'block';
                document.getElementById('confirmAddButtonText').textContent = 'Create & Add';
            } else {
                select.innerHTML = datasets.map(d => `
                    <option value="${d.id}">${Utils.escapeHtml(d.name)} (${d.file_count} files)</option>
                `).join('');
            }

            // Update count display
            document.getElementById('selectedFilesCount').textContent = this.selectedFiles.size;

            // Show the modal
            const modal = new bootstrap.Modal(document.getElementById('selectDatasetModal'));
            modal.show();

        } catch (error) {
            Utils.showToast('Failed to load datasets: ' + error.message, 'error');
        }
    },

    /**
     * Confirm adding selected files to dataset (called from modal)
     */
    async confirmAddToDataset() {
        const isCreateMode = document.getElementById('modeCreateNew').checked;

        try {
            let datasetId;
            let datasetName;

            if (isCreateMode) {
                // Create new dataset mode
                const name = document.getElementById('newDatasetName').value.trim();
                const description = document.getElementById('newDatasetDescription').value.trim() || null;

                if (!name) {
                    Utils.showToast('Please enter a dataset name', 'warning');
                    return;
                }

                // Create the dataset first
                const dataset = await API.createDataset(name, description);
                datasetId = dataset.id;
                datasetName = dataset.name;
                Utils.log('info', 'folders', `Created new dataset: id=${datasetId}, name='${datasetName}'`);

            } else {
                // Select existing dataset mode
                datasetId = document.getElementById('selectDatasetList').value;
                if (!datasetId) {
                    Utils.showToast('Please select a dataset', 'warning');
                    return;
                }
                datasetName = document.getElementById('selectDatasetList').selectedOptions[0].text;
            }

            // Add files to the dataset
            const result = await API.addFilesToDataset(datasetId, Array.from(this.selectedFiles));

            if (isCreateMode) {
                Utils.showToast(`Created dataset and added ${result.added} files`, 'success');
            } else {
                Utils.showToast(`Added ${result.added} files to dataset`, 'success');
            }

            // Close modal
            bootstrap.Modal.getInstance(document.getElementById('selectDatasetModal')).hide();

            // Mark that the dataset needs refresh (will be picked up when switching to datasets view)
            Datasets.needsRefresh = true;
            Datasets.lastModifiedDatasetId = datasetId;

            // Clear selection
            this.selectedFiles.clear();
            this.updateSelectionUI();

            // Refresh the grid to update selection state
            document.querySelectorAll('#imageGrid .image-card.selected').forEach(card => {
                card.classList.remove('selected');
                card.querySelector('.select-checkbox').checked = false;
            });

        } catch (error) {
            Utils.showToast('Failed to add files: ' + error.message, 'error');
        }
    },

    /**
     * Delete selected files
     */
    async addFilesToDataset(datasetId, fileIds) {
        // ... (existing code, not modifying this, just context anchor) ...
    },

    /**
     * Soft delete files (Undoable)
     */
    // --- Trash Bin Management ---

    loadTrash() {
        const saved = localStorage.getItem('cf_trash_bin');
        if (saved) {
            try { this.trashBin = JSON.parse(saved); } catch (e) { console.error('Trash load error', e); this.trashBin = []; }
        }
        const limit = localStorage.getItem('cf_trash_limit');
        if (limit) this.trashLimit = parseInt(limit);
        this.updateTrashCount();
    },

    saveTrash() {
        localStorage.setItem('cf_trash_bin', JSON.stringify(this.trashBin));
        this.updateTrashCount();
    },

    updateTrashCount() {
        const badge = document.getElementById('trash-count');
        if (badge) badge.innerText = this.trashBin.length;
    },

    /**
     * Soft delete files (Move to Trash)
     */
    async softDelete(fileIds, fromRedo = false) {
        if (!fileIds || fileIds.length === 0) return;

        const timestamp = Date.now();
        let addedCount = 0;

        fileIds.forEach(id => {
            const file = this.files.find(f => f.id === id);
            // If checking fromRedo or if file exists
            if (!file && !fromRedo) return;

            // Prevent duplicates
            if (this.trashBin.find(t => t.id === id)) return;

            // Construct trash item
            const item = {
                id: id,
                url: file ? (file.thumbnail_url || file.url || API.getImageUrl(id)) : API.getImageUrl(id),
                name: file ? file.name : 'Unknown',
                timestamp
            };

            this.trashBin.push(item);
            addedCount++;

            // Remove from UI immediately
            this.files = this.files.filter(f => f.id !== id);
            const card = document.querySelector(`.image-card[data-file-id="${id}"]`);
            if (card) card.remove();
        });

        if (addedCount > 0) {
            this.saveTrash();
            this.pruneTrash(); // Async
            this.updateSelectionUI();

            // Show toast with Undo action
            // Show toast with Undo action
            const msg = i18n.t('trash_moved').replace('{n}', addedCount);
            Utils.showToast(msg, 'info');
        }

        this.selectedFiles.clear();
        this.updateSelectionUI();
    },

    /**
     * Commit deletion to backend
     */
    /**
     * Enforce trash limit
     */
    async pruneTrash() {
        let pruned = 0;
        while (this.trashBin.length > this.trashLimit) {
            const oldest = this.trashBin.shift(); // Remove oldest (index 0)
            try {
                await API.deleteFile(oldest.id);
                console.log('[Trash] Pruned (Perm Delete):', oldest.id);
                pruned++;
            } catch (e) {
                console.error('[Trash] Failed to prune:', oldest.id, e);
            }
        }
        if (pruned > 0) this.saveTrash();
    },

    /**
     * Undo Method: Restore most recent from Trash
     */
    async undoDelete() {
        if (this.trashBin.length === 0) {
            Utils.showToast(i18n.t('trash_undo_empty'), 'warning');
            return;
        }

        // Pop the last item (LIFO for Undo)
        const item = this.trashBin.pop();
        this.saveTrash();

        // Reload to restore state
        await this.loadFiles();

        Utils.showToast(i18n.t('trash_restored'), 'success');
    },

    /**
     * Redo Method: Info only
     */
    redoDelete() {
        Utils.showToast(i18n.t('trash_redo_hint'), 'info');
    },

    // --- Actions ---

    openTrashModal() {
        const modalEl = document.getElementById('trashModal');
        const modal = new bootstrap.Modal(modalEl);
        this.renderTrashGrid();
        modal.show();
    },

    renderTrashGrid() {
        const grid = document.getElementById('trashGrid');
        grid.innerHTML = '';

        if (this.trashBin.length === 0) {
            grid.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-trash display-4 d-block mb-3 opacity-25"></i>
                    <p>${i18n.t('trash_is_empty')}</p>
                </div>`;
            document.getElementById('trashEmptyBtn').disabled = true;
            document.getElementById('trashRestoreAllBtn').disabled = true;
            return;
        }

        document.getElementById('trashEmptyBtn').disabled = false;
        document.getElementById('trashRestoreAllBtn').disabled = false;

        this.trashBin.slice().reverse().forEach(item => { // Show newest first
            const div = document.createElement('div');
            div.className = 'card bg-secondary bg-opacity-10 border-secondary position-relative d-inline-block m-2';
            div.style.width = '140px';
            div.innerHTML = `
                <img src="${item.url}" class="card-img-top" style="height: 140px; object-fit: cover; opacity: 0.7;">
                <div class="card-body p-2 text-truncate small text-muted">
                    ${item.name || item.id}
                </div>
                <div class="position-absolute top-0 start-0 m-1">
                    <input type="checkbox" class="form-check-input trash-selector" value="${item.id}">
                </div>
            `;
            // Click to toggle
            div.onclick = (e) => {
                if (e.target.tagName !== 'INPUT') {
                    const cb = div.querySelector('input');
                    cb.checked = !cb.checked;
                }
                this.updateTrashButtons();
            };
            grid.appendChild(div);
        });

        // Bind selectors
        grid.querySelectorAll('.trash-selector').forEach(cb => {
            cb.addEventListener('change', () => this.updateTrashButtons());
        });
        this.updateTrashButtons();
    },

    updateTrashButtons() {
        const checked = document.querySelectorAll('.trash-selector:checked').length;
        document.getElementById('trashRestoreSelectedBtn').disabled = checked === 0;
        document.getElementById('trashDeleteSelectedBtn').disabled = checked === 0;
        document.getElementById('trashRestoreSelectedBtn').innerHTML = `<i class="bi bi-arrow-counterclockwise me-1"></i> ${i18n.t('trash_restore_selected')} (${checked})`;
    },

    async emptyTrash() {
        if (!confirm(i18n.t('trash_confirm_empty'))) return;

        const count = this.trashBin.length;
        Utils.showToast(i18n.t('js_processing'), 'info');

        const modalInstance = bootstrap.Modal.getInstance(document.getElementById('trashModal'));

        // Parallel or Serial? Serial safe.
        for (const item of this.trashBin) {
            try { await API.deleteFile(item.id); } catch (e) { }
        }

        this.trashBin = [];
        this.saveTrash();
        this.renderTrashGrid();
        this.trashBin = [];
        this.saveTrash();
        this.renderTrashGrid();
        Utils.showToast(i18n.t('delete_success'), 'success');
    },

    async restoreTrashItems(ids) {
        if (!ids || ids.length === 0) return;

        const modalEl = document.getElementById('trashModal');
        // Filter out restored items from bin
        this.trashBin = this.trashBin.filter(item => !ids.includes(item.id));
        this.saveTrash();

        // Refresh UI
        this.renderTrashGrid();
        await this.loadFiles(); // Refresh main view to see restored

        const msg = i18n.t('trash_restored_count').replace('{n}', ids.length);
        Utils.showToast(msg, 'success');
    },

    async deleteTrashItems(ids) {
        if (!ids || ids.length === 0) return;

        const message = i18n.t('trash_confirm_delete_selected').replace('{n}', ids.length);
        if (!confirm(message)) return;

        for (const id of ids) {
            try { await API.deleteFile(id); } catch (e) { }
        }

        // Remove from bin
        this.trashBin = this.trashBin.filter(item => !ids.includes(item.id));
        this.saveTrash();
        this.renderTrashGrid();
    },

    /**
     * Delete selected files
     */
    async deleteSelectedFiles() {
        const count = this.selectedFiles.size;
        if (count === 0) return;

        const suppressConfirm = localStorage.getItem('cf_suppress_delete_confirm') === 'true';

        if (!suppressConfirm) {
            const message = i18n.t('confirm_delete_msg').replace('{n}', count);
            const { confirmed, checked } = await Utils.confirmWithCheckbox(
                message,
                i18n.t('confirm_delete_title'),
                i18n.t('dont_ask_again')
            );
            if (!confirmed) return;
            if (checked) {
                localStorage.setItem('cf_suppress_delete_confirm', 'true');
            }
        }

        // Proceed with Soft Delete (Undoable)
        this.softDelete(Array.from(this.selectedFiles));
    },

    /**
     * Delete a single file
     */
    async deleteSingleFile(fileId) {
        if (!fileId) return;

        // Check user strictness for confirmation
        const suppressConfirm = localStorage.getItem('cf_suppress_delete_confirm') === 'true';

        if (!suppressConfirm) {
            const title = (typeof i18n !== 'undefined') ? i18n.t('confirm_delete_title') : 'Confirm Delete';
            const checkboxLabel = (typeof i18n !== 'undefined') ? i18n.t('dont_ask_again') : "Don't ask again";

            const { confirmed, checked } = await Utils.confirmWithCheckbox(
                'Delete this file permanently?',
                title,
                checkboxLabel
            );

            if (!confirmed) return;

            if (checked) {
                localStorage.setItem('cf_suppress_delete_confirm', 'true');
            }
        }

        // Close modal if open
        const modalEl = document.getElementById('imageDetailModal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();

        // Proceed with Soft Delete
        this.softDelete([fileId]);
    },

    /**
     * Show image details modal
     */
    async showImageDetails(fileId) {
        // Save current file ID for navigation
        this.currentDetailFileId = fileId;

        let modal = bootstrap.Modal.getInstance(document.getElementById('imageDetailModal'));
        if (!modal) {
            modal = new bootstrap.Modal(document.getElementById('imageDetailModal'));
        }

        try {
            const file = await API.getFileDetails(fileId);

            document.getElementById('imageDetailTitle').textContent = file.filename;
            const imageUrl = API.getImageUrl(fileId);
            document.getElementById('imageDetailPreview').src = imageUrl;

            // Sync fullscreen if active
            const fullscreenOverlay = document.getElementById('fullscreenOverlay');
            if (fullscreenOverlay && !fullscreenOverlay.classList.contains('d-none')) {
                document.getElementById('fullscreenImage').src = imageUrl;
            }

            // File info table
            document.getElementById('imageDetailInfo').innerHTML = `
                <tr><td>Filename</td><td>${Utils.escapeHtml(file.filename)}</td></tr>
                <tr><td>Path</td><td><small>${Utils.escapeHtml(file.relative_path)}</small></td></tr>
                <tr><td>Dimensions</td><td>${file.width} × ${file.height}</td></tr>
                <tr><td>Size</td><td>${Utils.formatBytes(file.file_size)}</td></tr>
                <tr><td>Format</td><td>${file.format}</td></tr>
                <tr><td>Added</td><td>${Utils.formatDate(file.discovered_date)}</td></tr>
            `;

            // Imported caption (read-only) - this is from the paired .txt file
            const captionArea = document.getElementById('imageDetailCaptionArea');
            if (file.imported_caption) {
                captionArea.innerHTML = `
                    <div class="alert alert-secondary mb-0">
                        <small class="text-muted d-block mb-1"><i class="bi bi-file-text me-1"></i>Imported from paired .txt file</small>
                        <div style="white-space: pre-wrap;">${Utils.escapeHtml(file.imported_caption)}</div>
                    </div>
                `;
            } else {
                captionArea.innerHTML = `
                    <div class="text-muted fst-italic">
                        <i class="bi bi-info-circle me-1"></i>No paired caption file found.
                        <br><small>Add a .txt file with the same name as the image to import a caption.</small>
                    </div>
                `;
            }

            // Show modal if not already shown
            if (!document.getElementById('imageDetailModal').classList.contains('show')) {
                modal.show();
            }

        } catch (error) {
            Utils.showToast('Failed to load file details: ' + error.message, 'error');
        }
    },

    /**
     * Save caption for current image in detail modal
     */
    async saveImageCaption() {
        const captionEl = document.getElementById('imageDetailCaption');
        const fileId = captionEl.dataset.fileId;
        const text = captionEl.value.trim();

        if (!fileId) {
            Utils.showToast('No file selected', 'warning');
            return;
        }

        try {
            // Update the imported_caption field on the file
            await API.request(`/files/${fileId}/caption`, {
                method: 'PUT',
                body: { text }
            });

            Utils.showToast('Caption saved', 'success');

            // Update the has_caption indicator if in the grid
            const card = document.querySelector(`[data-file-id="${fileId}"]`);
            if (card && text) {
                let badge = card.querySelector('.caption-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'badge bg-success caption-badge';
                    badge.innerHTML = '<i class="bi bi-chat-quote-fill"></i>';
                    card.appendChild(badge);
                }
            }

        } catch (error) {
            Utils.showToast('Failed to save caption: ' + error.message, 'error');
        }
    },

    /**
     * Generate caption for current image using vision model
     */
    async generateSingleCaption() {
        const captionEl = document.getElementById('imageDetailCaption');
        const fileId = captionEl.dataset.fileId;

        if (!fileId) {
            Utils.showToast('No file selected', 'warning');
            return;
        }

        const btn = document.getElementById('generateImageCaption');
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';

        try {
            const result = await API.generateCaption(fileId);
            captionEl.value = result.caption;
            Utils.showToast('Caption generated', 'success');

        } catch (error) {
            Utils.showToast('Failed to generate caption: ' + error.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    },

    /**
     * Show edit folder modal
     */
    async showEditFolderModal(folderId) {
        try {
            const folder = await API.getFolder(folderId);

            document.getElementById('editFolderId').value = folder.id;
            document.getElementById('editFolderPath').value = folder.path;
            document.getElementById('editFolderName').value = folder.name || '';
            document.getElementById('editFolderEnabled').checked = folder.enabled !== false;

            const modal = new bootstrap.Modal(document.getElementById('editFolderModal'));
            modal.show();
        } catch (error) {
            Utils.showToast('Failed to load folder: ' + error.message, 'error');
        }
    },

    /**
     * Save edited folder
     */
    async saveEditFolder() {
        const folderId = document.getElementById('editFolderId').value;
        const name = document.getElementById('editFolderName').value.trim() || null;
        const enabled = document.getElementById('editFolderEnabled').checked;

        const btn = document.getElementById('confirmEditFolder');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving...';

        try {
            await API.updateFolder(folderId, { name, enabled });
            Utils.showToast('Folder updated successfully', 'success');

            bootstrap.Modal.getInstance(document.getElementById('editFolderModal')).hide();
            await this.loadFolders();

        } catch (error) {
            Utils.showToast('Failed to update folder: ' + error.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Changes';
        }
    },

    /**
     * Rescan a folder
     */
    async rescanFolder(folderId) {
        const btn = event.target.closest('.rescan-btn');
        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const result = await API.scanFolder(folderId);
            Utils.showToast(`Scan complete: ${result.files_added} added, ${result.files_updated} updated, ${result.files_removed} removed`, 'success');

            // Immediately refresh the folder list and files if this folder is selected
            await this.loadFolders();

            if (this.currentFolderId === folderId) {
                // Update the file count in the header immediately
                const folder = await API.getFolder(folderId);
                document.getElementById('fileCount').textContent = `${folder.file_count} files`;

                // Reload the files
                await this.loadFolderFiles(folderId, 1, document.getElementById('fileFilterType').value, true);
            }

        } catch (error) {
            Utils.showToast('Failed to scan folder: ' + error.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    },

    /**
     * Remove a folder
     */
    async removeFolder(folderId) {
        if (!await Utils.confirm('Remove this folder from tracking? (Files will not be deleted)')) {
            return;
        }

        try {
            await API.removeFolder(folderId);
            Utils.showToast('Folder removed', 'success');

            if (this.currentFolderId === folderId) {
                this.currentFolderId = null;
                document.getElementById('imageGrid').innerHTML = Utils.emptyState('bi-images', 'Select a folder to view images');
                document.getElementById('folderTitle').innerHTML = '<i class="bi bi-image me-2"></i>Select a folder';
                document.getElementById('fileCount').textContent = '';
            }

            await this.loadFolders();

        } catch (error) {
            Utils.showToast('Failed to remove folder: ' + error.message, 'error');
        }
    },

    /**
     * Render pagination controls
     */
    renderPagination(total, currentPage) {
        const totalPages = Math.ceil(total / this.pageSize);
        const pagination = document.getElementById('imagePagination');

        if (totalPages <= 1) {
            pagination.style.display = 'none';
            return;
        }

        pagination.style.display = 'block';
        const ul = pagination.querySelector('ul');

        let html = '';

        // Previous button
        html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${currentPage - 1}">Previous</a>
        </li>`;

        // Page numbers
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
                html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>`;
            } else if (i === currentPage - 3 || i === currentPage + 3) {
                html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
        }

        // Next button
        html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${currentPage + 1}">Next</a>
        </li>`;

        ul.innerHTML = html;

        // Bind events
        ul.querySelectorAll('[data-page]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const page = parseInt(el.dataset.page);
                if (page >= 1 && page <= totalPages && page !== currentPage) {
                    const filter = document.getElementById('fileFilterType').value;
                    this.loadFolderFiles(this.currentFolderId, page, filter);
                }
            });
        });
    }
};

// Make available globally
window.Folders = Folders;