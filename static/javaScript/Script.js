/* =========================================================
   HMS – Centralized Theme Management System
   Handles Theme Color, Light/Dark/System Toggle, Anti-Flash,
   Live In-Memory Variable Updates, Debounce Guard, and Persistence
   ========================================================= */
(function () {
  var THEME_KEY = 'hms_theme';
  var lastToggleTime = 0;

  function getSystemTheme() {
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }

  function hexToRgb(hex) {
    if (!hex) return '99, 102, 241';
    var clean = hex.trim().replace('#', '');
    if (clean.length === 3) {
      clean = clean.split('').map(function(c) { return c + c; }).join('');
    }
    if (clean.length !== 6) return '99, 102, 241';
    var r = parseInt(clean.substring(0, 2), 16);
    var g = parseInt(clean.substring(2, 4), 16);
    var b = parseInt(clean.substring(4, 6), 16);
    return isNaN(r) || isNaN(g) || isNaN(b) ? '99, 102, 241' : (r + ', ' + g + ', ' + b);
  }

  function hexToHover(hex) {
    if (!hex) return '#4f46e5';
    var clean = hex.trim().replace('#', '');
    if (clean.length === 3) {
      clean = clean.split('').map(function(c) { return c + c; }).join('');
    }
    if (clean.length !== 6) return '#4f46e5';
    var r = Math.max(0, Math.floor(parseInt(clean.substring(0, 2), 16) * 0.85));
    var g = Math.max(0, Math.floor(parseInt(clean.substring(2, 4), 16) * 0.85));
    var b = Math.max(0, Math.floor(parseInt(clean.substring(4, 6), 16) * 0.85));
    var toHex = function(n) { var s = n.toString(16); return s.length === 1 ? '0' + s : s; };
    return '#' + toHex(r) + toHex(g) + toHex(b);
  }

  // Update dynamic CSS variables in real time (for live previews and color pickers)
  window.updateDynamicThemeColor = function(hex) {
    if (!hex) return;
    var root = document.documentElement;
    var rgb = hexToRgb(hex);
    var hover = hexToHover(hex);

    root.style.setProperty('--theme-hex', hex);
    root.style.setProperty('--theme-hex-rgb', rgb);
    root.style.setProperty('--theme-hex-hover', hover);
    root.style.setProperty('--theme-hex-glow', 'rgba(' + rgb + ', 0.35)');
    root.style.setProperty('--theme-hex-subtle', 'rgba(' + rgb + ', 0.12)');
    root.style.setProperty('--primary', hex);
    root.style.setProperty('--primary-rgb', rgb);
    root.style.setProperty('--primary-hover', hover);
    root.style.setProperty('--primary-glow', 'rgba(' + rgb + ', 0.35)');

    // Sync meta theme-color tag
    var metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', hex);
  };

  // Global theme applicator (Dark / Light / System)
  window.applyThemeMode = function (theme) {
    var actualTheme = theme;
    if (theme === 'system') {
      actualTheme = getSystemTheme();
    }
    if (actualTheme !== 'dark' && actualTheme !== 'light') {
      actualTheme = 'light';
    }

    document.documentElement.setAttribute('data-theme', actualTheme);
    try {
      localStorage.setItem(THEME_KEY, actualTheme);
    } catch (e) {}

    // Sync all theme icons (Sun shows in dark mode to switch to light; Moon in light mode to switch to dark)
    var icons = document.querySelectorAll('#themeIcon, .theme-icon');
    icons.forEach(function(icon) {
      if (actualTheme === 'dark') {
        icon.className = 'bi bi-sun-fill text-warning';
      } else {
        icon.className = 'bi bi-moon-fill text-primary';
      }
    });

    // Sync all theme toggle button titles / accessibility attributes
    var buttons = document.querySelectorAll('#themeToggleBtn, .theme-toggle-btn');
    buttons.forEach(function(btn) {
      var titleText = actualTheme === 'dark' ? 'Switch to Light Theme' : 'Switch to Dark Theme';
      btn.setAttribute('title', titleText);
      btn.setAttribute('aria-label', titleText);
    });

    // Sync all theme labels
    var labels = document.querySelectorAll('#themeLabel, .theme-label');
    labels.forEach(function(label) {
      label.textContent = actualTheme.charAt(0).toUpperCase() + actualTheme.slice(1);
    });

    // Dispatch custom event for widgets/charts to adapt
    try {
      window.dispatchEvent(new CustomEvent('hms:themechange', { detail: { theme: actualTheme } }));
    } catch (e) {}
  };

  // Direct toggle between dark and light with 300ms debounce guard
  window.themeToggleHandler = function(e) {
    if (e) {
      if (typeof e.preventDefault === 'function') e.preventDefault();
      if (typeof e.stopPropagation === 'function') e.stopPropagation();
    }
    var now = Date.now();
    if (now - lastToggleTime < 300) return;
    lastToggleTime = now;

    var current = document.documentElement.getAttribute('data-theme') || localStorage.getItem(THEME_KEY) || window.HMS_SERVER_DEFAULT_THEME || 'light';
    var target = (current === 'dark') ? 'light' : 'dark';
    window.applyThemeMode(target);
  };

  // Global event delegation for theme toggle buttons
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('#themeToggleBtn, .theme-toggle-btn');
    if (btn) {
      window.themeToggleHandler(e);
    }
  });

  // Listen for system preference changes
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
      if (localStorage.getItem(THEME_KEY) === 'system') {
        window.applyThemeMode('system');
      }
    });
  }

  // Initial setup: resolve stored preference or system default
  var defaultTheme = window.HMS_SERVER_DEFAULT_THEME || 'light';
  var initialTheme = localStorage.getItem(THEME_KEY) || defaultTheme;
  window.applyThemeMode(initialTheme);

  // Re-verify on DOM ready
  document.addEventListener('DOMContentLoaded', function () {
    var stored = localStorage.getItem(THEME_KEY) || window.HMS_SERVER_DEFAULT_THEME || 'light';
    window.applyThemeMode(stored);
  });
})();

/* =========================================================
   HMS — AJAX Polling Engine with Exponential Backoff
   Updates statistics in real-time, respects tab focus logic
   ========================================================= */
(function() {
  // Only execute polling on the superadmin dashboard path
  if (!window.location.pathname.includes('/superadmin/')) return;

  const POLLING_URL = '/superadmin/ajax/live-stats/';
  const DEFAULT_INTERVAL = 15000; // 15 seconds
  let pollInterval = DEFAULT_INTERVAL;
  let pollTimeout = null;
  let previousData = {};
  
  const refreshStatus = document.getElementById('live-refresh-status');
  
  function flashElement(el, colorClass) {
    if (!el) return;
    el.classList.remove('glow-update', 'glow-pulse-blue', 'glow-pulse-green', 'glow-pulse-purple', 'glow-pulse-orange', 'glow-pulse-cyan', 'glow-pulse-yellow');
    void el.offsetWidth; // trigger reflow
    el.classList.add(colorClass || 'glow-update');
    setTimeout(() => {
      el.classList.remove(colorClass || 'glow-update');
    }, 1500);
  }

  function animateNumberValue(el, targetVal, formatRupee = false) {
    if (!el) return;
    let startVal = parseFloat(el.textContent.replace(/[^\d.]/g, '')) || 0;
    if (startVal === targetVal) {
      if (formatRupee) el.textContent = '₹' + targetVal.toLocaleString();
      else el.textContent = targetVal.toLocaleString();
      return;
    }
    
    let duration = 800; // 0.8s animate timing
    let startTime = null;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      let progress = Math.min((timestamp - startTime) / duration, 1);
      // easeOutQuad
      let eased = progress * (2 - progress);
      let current = Math.floor(startVal + eased * (targetVal - startVal));
      
      if (formatRupee) el.textContent = '₹' + current.toLocaleString();
      else el.textContent = current.toLocaleString();
      
      if (progress < 1) {
        window.requestAnimationFrame(step);
      } else {
        if (formatRupee) el.textContent = '₹' + targetVal.toLocaleString();
        else el.textContent = targetVal.toLocaleString();
      }
    }
    window.requestAnimationFrame(step);
  }

  function updateDashboard(data) {
    // 1. Total Students
    const elStudents = document.getElementById('kpi-total-students');
    if (elStudents && previousData.total_students !== data.total_students) {
      animateNumberValue(elStudents, data.total_students);
      flashElement(elStudents, 'glow-pulse-blue');
    }
    const elStudentsSub = document.getElementById('kpi-students-sub');
    if (elStudentsSub) {
      elStudentsSub.textContent = `${data.active_students} active · ${data.inactive_students} inactive`;
    }

    // 2. Occupied Beds
    const elBeds = document.getElementById('kpi-occupied-beds');
    if (elBeds && previousData.occupied_beds !== data.occupied_beds) {
      animateNumberValue(elBeds, data.occupied_beds);
      flashElement(elBeds, 'glow-pulse-green');
    }
    const elProgress = document.getElementById('kpi-occupancy-progress');
    if (elProgress) {
      elProgress.setAttribute('data-width', data.occupancy_pct);
      elProgress.style.width = data.occupancy_pct + '%';
    }
    const elBedsSub = document.getElementById('kpi-occupancy-sub');
    if (elBedsSub) {
      elBedsSub.textContent = `${data.occupancy_pct}% occupancy · ${data.vacant_beds} vacant`;
    }

    // 3. Monthly Revenue
    const elRevenue = document.getElementById('kpi-monthly-revenue');
    if (elRevenue && previousData.monthly_revenue !== data.monthly_revenue) {
      animateNumberValue(elRevenue, data.monthly_revenue, true);
      flashElement(elRevenue, 'glow-pulse-purple');
    }
    const elRevenueSub = document.getElementById('kpi-revenue-sub');
    if (elRevenueSub) {
      elRevenueSub.textContent = `₹${data.today_revenue} today`;
    }

    // 4. Open Complaints
    const elComplaints = document.getElementById('kpi-open-complaints');
    if (elComplaints && previousData.open_complaints !== data.open_complaints) {
      animateNumberValue(elComplaints, data.open_complaints);
      flashElement(elComplaints, 'glow-pulse-orange');
    }
    const elComplaintsSub = document.getElementById('kpi-complaints-sub');
    if (elComplaintsSub) {
      elComplaintsSub.textContent = `${data.resolved_complaints} resolved total`;
    }

    // 6. Total Staff
    const elStaff = document.getElementById('kpi-total-staff');
    if (elStaff && previousData.total_staff !== data.total_staff) {
      animateNumberValue(elStaff, data.total_staff);
      flashElement(elStaff, 'glow-pulse-yellow');
    }
    const elStaffSub = document.getElementById('kpi-staff-sub');
    if (elStaffSub) {
      elStaffSub.textContent = `${data.active_staff} active`;
    }

    // Lower KPIs
    const elTotalUsers = document.getElementById('kpi-total-users');
    if (elTotalUsers && previousData.total_users !== data.total_users) {
      animateNumberValue(elTotalUsers, data.total_users);
    }
    const elActiveUsers = document.getElementById('kpi-active-users');
    if (elActiveUsers && previousData.active_users !== data.active_users) {
      animateNumberValue(elActiveUsers, data.active_users);
    }
    const elPendingLeaves = document.getElementById('kpi-pending-leaves');
    if (elPendingLeaves && previousData.pending_leaves !== data.pending_leaves) {
      animateNumberValue(elPendingLeaves, data.pending_leaves);
    }

    // Disk health
    const elDiskText = document.getElementById('kpi-disk-text');
    if (elDiskText) {
      elDiskText.textContent = `Disk: ${data.disk_used_gb} GB / ${data.disk_total_gb} GB`;
    }
    const elDiskPctText = document.getElementById('kpi-disk-pct-text');
    if (elDiskPctText) {
      elDiskPctText.textContent = `${data.disk_pct}%`;
    }
    const elDiskProgress = document.getElementById('kpi-disk-progress');
    if (elDiskProgress) {
      elDiskProgress.setAttribute('data-width', data.disk_pct);
      elDiskProgress.style.width = data.disk_pct + '%';
    }

    previousData = data;
    if (refreshStatus) {
      const now = new Date();
      refreshStatus.textContent = `Live Stats: updated ${now.toLocaleTimeString()}`;
    }
  }

  function fetchStats() {
    // If window is hidden, defer polling to save battery and resource costs
    if (document.visibilityState === 'hidden') {
      pollTimeout = setTimeout(fetchStats, DEFAULT_INTERVAL);
      return;
    }

    fetch(POLLING_URL, {
      headers: {
        'x-requested-with': 'XMLHttpRequest'
      }
    })
    .then(response => {
      if (!response.ok) throw new Error('HTTP Status ' + response.status);
      return response.json();
    })
    .then(data => {
      updateDashboard(data);
      pollInterval = DEFAULT_INTERVAL; // Reset polling backoff on success
      
      const badge = document.querySelector('.badge-live');
      if (badge) {
        badge.style.background = 'rgba(34,197,94,0.2)';
        badge.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size:6px;"></i>LIVE';
      }
    })
    .catch(error => {
      console.warn('Real-time Polling failed:', error);
      // Exponential backoff up to 2 minutes maximum
      pollInterval = Math.min(pollInterval * 1.5, 120000);
      
      const badge = document.querySelector('.badge-live');
      if (badge) {
        badge.style.background = 'rgba(239,68,68,0.2)';
        badge.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-1" style="font-size:8px;"></i>RECONNECTING';
      }
    })
    .finally(() => {
      pollTimeout = setTimeout(fetchStats, pollInterval);
    });
  }

  // Handle sudden focus gain
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      clearTimeout(pollTimeout);
      fetchStats();
    }
  });

  // Start initial polling
  pollTimeout = setTimeout(fetchStats, DEFAULT_INTERVAL);
})();
