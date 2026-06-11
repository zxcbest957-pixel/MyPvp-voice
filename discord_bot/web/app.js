document.addEventListener('DOMContentLoaded', () => {
    // State Variables
    let currentGuildId = null;
    let leaderboardData = [];
    let activeTab = 'all';
    let searchQuery = '';

    // DOM Elements
    const guildSelect = document.getElementById('guild-select');
    const serverNameEl = document.getElementById('server-name');
    const serverAvatar = document.getElementById('server-avatar');
    const serverAvatarFallback = document.getElementById('server-avatar-fallback');
    
    // Overview Stats
    const totalMembersEl = document.getElementById('stat-total-members');
    const totalMessagesEl = document.getElementById('stat-total-messages');
    const totalVoiceEl = document.getElementById('stat-total-voice');

    // Filters and search
    const tabButtons = document.querySelectorAll('.tab-btn');
    const userSearch = document.getElementById('user-search');

    // List elements
    const leaderboardList = document.getElementById('leaderboard-list');
    const loader = document.getElementById('loader');
    const emptyState = document.getElementById('empty-state');

    // Initial load
    init();

    async function init() {
        setupEventListeners();
        await fetchGuilds();
    }

    function setupEventListeners() {
        // Dropdown guild selector
        guildSelect.addEventListener('change', (e) => {
            currentGuildId = e.target.value;
            fetchStats(currentGuildId);
        });

        // Search input
        userSearch.addEventListener('input', (e) => {
            searchQuery = e.target.value.toLowerCase().trim();
            renderLeaderboard();
        });

        // Navigation Tabs
        tabButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                tabButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                activeTab = btn.getAttribute('data-tab');
                renderLeaderboard();
            });
        });

        // Close modal handlers
        const modal = document.getElementById('user-modal');
        const closeBtn = document.getElementById('modal-close');
        
        const closeModal = () => {
            modal.classList.remove('active');
            setTimeout(() => {
                modal.style.display = 'none';
            }, 300);
        };

        closeBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                closeModal();
            }
        });
    }

    // Fetch list of guilds this bot is active on
    async function fetchGuilds() {
        try {
            const response = await fetch('/api/guilds');
            const guilds = await response.json();
            
            guildSelect.innerHTML = '';
            
            if (guilds.length === 0) {
                serverNameEl.textContent = "Нет доступных серверов";
                loader.style.display = 'none';
                emptyState.style.display = 'flex';
                return;
            }

            guilds.forEach(guild => {
                const option = document.createElement('option');
                option.value = guild.id;
                option.textContent = guild.name;
                guildSelect.appendChild(option);
            });

            // Check if there is a guild_id parameter in the URL
            const urlParams = new URLSearchParams(window.location.search);
            const queryGuildId = urlParams.get('guild_id');
            
            let selectedGuildId = guilds[0].id;
            // Validate if the queryGuildId is in the fetched guilds list
            if (queryGuildId && guilds.some(g => g.id === queryGuildId)) {
                selectedGuildId = queryGuildId;
            }
            
            guildSelect.value = selectedGuildId;
            currentGuildId = selectedGuildId;
            fetchStats(currentGuildId);
        } catch (error) {
            console.error('Error fetching guilds:', error);
            serverNameEl.textContent = "Ошибка загрузки";
            loader.style.display = 'none';
        }
    }

    // Fetch stats for specific guild
    async function fetchStats(guildId) {
        loader.style.display = 'flex';
        leaderboardList.innerHTML = '';
        emptyState.style.display = 'none';

        try {
            const response = await fetch(`/api/stats?guild_id=${guildId}`);
            const data = await response.json();
            
            // Update Server header info
            serverNameEl.textContent = data.guildName || 'Discord Server';
            if (data.guildIcon) {
                serverAvatar.src = data.guildIcon;
                serverAvatar.style.display = 'block';
                serverAvatarFallback.style.display = 'none';
            } else {
                serverAvatar.style.display = 'none';
                serverAvatarFallback.style.display = 'flex';
                serverAvatarFallback.textContent = (data.guildName || 'DS').substring(0, 2).toUpperCase();
            }

            // Update Overview Stats
            totalMembersEl.textContent = formatNumber(data.totalMembers);
            totalMessagesEl.textContent = formatNumber(data.totalMessages);
            totalVoiceEl.textContent = formatVoiceTime(data.totalVoiceSeconds);

            // Store user list
            leaderboardData = data.leaderboard || [];
            
            // Render voice sidebar
            renderVoiceSidebar(data.voiceStates || []);
            
            loader.style.display = 'none';
            renderLeaderboard();
        } catch (error) {
            console.error('Error fetching guild stats:', error);
            loader.style.display = 'none';
            emptyState.style.display = 'flex';
        }
    }

    // Render leaderboard lists based on current filters, tabs, searches
    function renderLeaderboard() {
        leaderboardList.innerHTML = '';
        
        // 1. Filter by search query
        let filtered = leaderboardData.filter(user => {
            const dispName = (user.globalName || '').toLowerCase();
            const userName = (user.username || '').toLowerCase();
            const uid = (user.userId || '');
            return dispName.includes(searchQuery) || userName.includes(searchQuery) || uid.includes(searchQuery);
        });

        // Calculate scores for custom sorting/rating
        // Score = Messages * 10 + VoiceMinutes * 10 (which is voiceSeconds / 6)
        filtered.forEach(user => {
            user.activeScore = Math.round(user.messagesCount * 10 + user.voiceSeconds / 6);
        });

        // 2. Sort depending on active tab
        if (activeTab === 'all') {
            filtered.sort((a, b) => b.activeScore - a.activeScore || b.messagesCount - a.messagesCount);
        } else if (activeTab === 'voice') {
            filtered.sort((a, b) => b.voiceSeconds - a.voiceSeconds);
        } else if (activeTab === 'messages') {
            filtered.sort((a, b) => b.messagesCount - a.messagesCount);
        }

        if (filtered.length === 0) {
            emptyState.style.display = 'flex';
            return;
        }
        emptyState.style.display = 'none';

        // Calculate max values for rendering progress rating bars
        const maxScore = Math.max(...leaderboardData.map(u => Math.round(u.messagesCount * 10 + u.voiceSeconds / 6)), 1);
        const maxVoice = Math.max(...leaderboardData.map(u => u.voiceSeconds), 1);
        const maxMessages = Math.max(...leaderboardData.map(u => u.messagesCount), 1);

        // 3. Render items
        filtered.forEach((user, index) => {
            const rank = index + 1;
            const item = document.createElement('div');
            item.className = 'leaderboard-item';

            // Rank Badge or Text
            let rankHTML = `<span class="rank-normal">${rank}</span>`;
            if (rank === 1) rankHTML = `<div class="rank-badge rank-1">1</div>`;
            else if (rank === 2) rankHTML = `<div class="rank-badge rank-2">2</div>`;
            else if (rank === 3) rankHTML = `<div class="rank-badge rank-3">3</div>`;

            // Avatar setup
            let avatarHTML = `<div class="default-avatar">${(user.globalName || user.username || 'U').charAt(0).toUpperCase()}</div>`;
            if (user.avatarUrl) {
                avatarHTML = `<img class="user-avatar" src="${user.avatarUrl}" alt="Avatar" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                              <div class="default-avatar" style="display:none;">${(user.globalName || user.username || 'U').charAt(0).toUpperCase()}</div>`;
            }

            // Progress Bar Calculation
            let progressPercent = 0;
            let ratingText = '';
            if (activeTab === 'all') {
                progressPercent = Math.min((user.activeScore / maxScore) * 100, 100);
                ratingText = `${user.activeScore} pts`;
            } else if (activeTab === 'voice') {
                progressPercent = Math.min((user.voiceSeconds / maxVoice) * 100, 100);
                ratingText = formatVoiceTime(user.voiceSeconds);
            } else if (activeTab === 'messages') {
                progressPercent = Math.min((user.messagesCount / maxMessages) * 100, 100);
                ratingText = `${user.messagesCount} смс`;
            }

            // Render columns
            item.innerHTML = `
                <div class="col-rank">${rankHTML}</div>
                <div class="col-user">
                    <div class="user-avatar-wrapper">${avatarHTML}</div>
                    <div class="user-names">
                        <span class="user-display-name">${escapeHTML(user.globalName || user.username)}</span>
                        <span class="user-username">@${escapeHTML(user.username)}</span>
                    </div>
                </div>
                <div class="col-rating">
                    <div class="rating-bar-container">
                        <div class="rating-bar" style="width: ${progressPercent}%"></div>
                    </div>
                    <span class="rating-value">${ratingText}</span>
                </div>
                <div class="col-messages">${formatNumber(user.messagesCount)}</div>
                <div class="col-voice">${formatVoiceTime(user.voiceSeconds)}</div>
                <div class="col-active">${formatRelativeTime(user.lastActive)}</div>
            `;

            // Bind click to open detailed modal
            item.addEventListener('click', () => {
                openUserModal(user);
            });

            leaderboardList.appendChild(item);
        });
    }

    // Helper functions
    function formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
        return num.toString();
    }

    function formatVoiceTime(seconds) {
        if (!seconds || seconds <= 0) return '0м';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        
        if (h > 0) {
            return `${h}ч ${m}м`;
        }
        return `${m}м`;
    }

    function formatRelativeTime(timestamp) {
        if (!timestamp || timestamp <= 0) return 'Неактивен';
        
        const now = Math.floor(Date.now() / 1000);
        const diff = now - timestamp;
        
        if (diff < 60) return 'Только что';
        
        const mins = Math.floor(diff / 60);
        if (mins < 60) {
            return `${mins} ${getRussianDeclension(mins, 'минуту', 'минуты', 'минут')} назад`;
        }
        
        const hours = Math.floor(mins / 60);
        if (hours < 24) {
            return `${hours} ${getRussianDeclension(hours, 'час', 'часа', 'часов')} назад`;
        }
        
        const days = Math.floor(hours / 24);
        if (days === 1) return 'Вчера';
        if (days === 2) return 'Позавчера';
        return `${days} ${getRussianDeclension(days, 'день', 'дня', 'дней')} назад`;
    }

    function getRussianDeclension(number, one, two, five) {
        let n = Math.abs(number);
        n %= 100;
        if (n >= 5 && n <= 20) {
            return five;
        }
        n %= 10;
        if (n === 1) {
            return one;
        }
        if (n >= 2 && n <= 4) {
            return two;
        }
        return five;
    }

    function escapeHTML(str) {
        if (!str) return '';
        return str.replace(/[&<>'"]/g, 
            tag => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                "'": '&#39;',
                '"': '&quot;'
            }[tag] || tag)
        );
    }

    async function openUserModal(user) {
        const modal = document.getElementById('user-modal');
        const banner = document.getElementById('modal-banner');
        
        const avatarImg = document.getElementById('modal-avatar');
        const avatarFallback = document.getElementById('modal-avatar-fallback');
        const statusBadge = document.getElementById('modal-status-badge');
        
        const displayNameEl = document.getElementById('modal-display-name');
        const usernameEl = document.getElementById('modal-username');
        const badgesEl = document.getElementById('modal-badges');
        
        const statMessages = document.getElementById('modal-stat-messages');
        const statVoice = document.getElementById('modal-stat-voice');
        const statJoined = document.getElementById('modal-stat-joined');
        const statCreated = document.getElementById('modal-stat-created');
        
        const rolesCount = document.getElementById('modal-roles-count');
        const rolesList = document.getElementById('modal-roles-list');

        // Reset details to show placeholders
        banner.style.background = 'linear-gradient(135deg, var(--accent-purple), var(--accent-cyan))';
        statusBadge.className = 'status-badge offline';
        badgesEl.innerHTML = '';
        statJoined.textContent = 'Загрузка...';
        statCreated.textContent = 'Загрузка...';
        rolesCount.textContent = '0';
        rolesList.innerHTML = '<div class="loader-container" style="padding: 10px 0;"><div class="spinner" style="width: 20px; height: 20px; border-width: 2px;"></div></div>';

        // Load basic cached profile information instantly
        displayNameEl.textContent = user.globalName || user.username;
        usernameEl.textContent = `@${user.username}`;
        
        if (user.avatarUrl) {
            avatarImg.src = user.avatarUrl;
            avatarImg.style.display = 'block';
            avatarFallback.style.display = 'none';
        } else {
            avatarImg.style.display = 'none';
            avatarFallback.style.display = 'flex';
            avatarFallback.textContent = (user.globalName || user.username).charAt(0).toUpperCase();
        }

        statMessages.textContent = formatNumber(user.messagesCount);
        statVoice.textContent = formatVoiceTime(user.voiceSeconds);

        // Reveal modal with display flex, then trigger css slide scale animation
        modal.style.display = 'flex';
        setTimeout(() => {
            modal.classList.add('active');
        }, 10);

        // Load live detailed Discord metadata asynchronously
        try {
            const response = await fetch(`/api/member?guild_id=${currentGuildId}&user_id=${user.userId}`);
            const data = await response.json();

            // Set presence status
            statusBadge.className = `status-badge ${data.status || 'offline'}`;

            // Parse formatted creation and joined dates
            statJoined.textContent = formatDate(data.joinedAt) || 'Не на сервере';
            statCreated.textContent = formatDate(data.createdAt) || '-';

            // Set Admin/Owner badges
            if (data.isOwner) {
                badgesEl.innerHTML += '<span class="badge-tag badge-owner">Владелец</span>';
            } else if (data.isAdmin) {
                badgesEl.innerHTML += '<span class="badge-tag badge-admin">Админ</span>';
            }

            // Build dynamic colored tags list for roles
            rolesList.innerHTML = '';
            const roles = data.roles || [];
            rolesCount.textContent = roles.length;

            if (roles.length === 0) {
                rolesList.innerHTML = '<span style="font-size: 0.85rem; color: var(--text-muted);">Нет ролей</span>';
            } else {
                // Adjust banner background to match highest priority role color
                if (roles[0].color && roles[0].color !== '#8b8d99') {
                    banner.style.background = roles[0].color;
                }

                roles.forEach(role => {
                    const tag = document.createElement('div');
                    tag.className = 'role-tag';
                    tag.innerHTML = `<span class="role-dot" style="background-color: ${role.color}"></span>${escapeHTML(role.name)}`;
                    rolesList.appendChild(tag);
                });
            }

        } catch (error) {
            console.error('Error fetching member details:', error);
            statJoined.textContent = 'Ошибка';
            statCreated.textContent = 'Ошибка';
            rolesList.innerHTML = '<span style="font-size: 0.85rem; color: #e74c3c;">Ошибка загрузки</span>';
        }
    }

    function formatDate(isoString) {
        if (!isoString) return null;
        try {
            const date = new Date(isoString);
            return date.toLocaleDateString('ru-RU', {
                day: 'numeric',
                month: 'short',
                year: 'numeric'
            });
        } catch (e) {
            return null;
        }
    }

    function renderVoiceSidebar(voiceStates) {
        const voiceList = document.getElementById('voice-channels-list');
        const emptyState = document.getElementById('voice-empty-state');
        
        voiceList.innerHTML = '';
        
        if (!voiceStates || voiceStates.length === 0) {
            emptyState.style.display = 'flex';
            voiceList.style.display = 'none';
            return;
        }
        
        emptyState.style.display = 'none';
        voiceList.style.display = 'flex';
        
        voiceStates.forEach(channel => {
            const channelItem = document.createElement('div');
            channelItem.className = 'voice-channel-item';
            
            let membersHTML = '';
            channel.members.forEach(member => {
                let avatarHTML = `<div class="voice-member-default-avatar">${(member.globalName || member.username || 'U').charAt(0).toUpperCase()}</div>`;
                if (member.avatarUrl) {
                    avatarHTML = `<img class="voice-member-avatar" src="${member.avatarUrl}" alt="Avatar" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                                  <div class="voice-member-default-avatar" style="display:none;">${(member.globalName || member.username || 'U').charAt(0).toUpperCase()}</div>`;
                }
                
                membersHTML += `
                    <div class="voice-member-row" data-user-id="${member.userId}" data-username="${escapeHTML(member.username)}" data-global-name="${escapeHTML(member.globalName)}" data-avatar-url="${member.avatarUrl}">
                        ${avatarHTML}
                        <span class="voice-member-name">${escapeHTML(member.globalName || member.username)}</span>
                    </div>
                `;
            });
            
            channelItem.innerHTML = `
                <div class="voice-channel-name">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>
                    <span>${escapeHTML(channel.channelName)}</span>
                </div>
                <div class="voice-channel-members">
                    ${membersHTML}
                </div>
            `;
            
            // Bind click handlers to member rows in the sidebar
            channelItem.querySelectorAll('.voice-member-row').forEach(row => {
                row.addEventListener('click', () => {
                    const userId = row.getAttribute('data-user-id');
                    const username = row.getAttribute('data-username');
                    const globalName = row.getAttribute('data-global-name');
                    const avatarUrl = row.getAttribute('data-avatar-url');
                    
                    const existingUser = leaderboardData.find(u => u.userId === userId);
                    const userObj = existingUser || {
                        userId: userId,
                        username: username,
                        globalName: globalName,
                        avatarUrl: avatarUrl,
                        messagesCount: 0,
                        voiceSeconds: 0
                    };
                    
                    openUserModal(userObj);
                });
            });
            
            voiceList.appendChild(channelItem);
        });
    }
});
