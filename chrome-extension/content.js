// ViewMagnet Chrome Extension Content Script
// Runs on YouTube pages to add ViewMagnet score overlay

(function() {
  'use strict';
  
  const API_BASE = 'http://localhost:8000';
  let currentVideoId = null;
  let scoreOverlay = null;
  
  // Initialize
  init();
  
  function init() {
    // Watch for navigation changes (YouTube is SPA)
    const observer = new MutationObserver(() => {
      const newVideoId = getVideoId();
      if (newVideoId && newVideoId !== currentVideoId) {
        currentVideoId = newVideoId;
        onVideoChange();
      }
    });
    
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    // Initial check
    currentVideoId = getVideoId();
    if (currentVideoId) {
      onVideoChange();
    }
  }
  
  function getVideoId() {
    const url = window.location.href;
    const match = url.match(/[?&]v=([^&]+)/);
    return match ? match[1] : null;
  }
  
  async function onVideoChange() {
    // Remove existing overlay
    removeOverlay();
    
    // Wait for video player to load
    await waitForElement('#movie_player');
    
    // Create and show overlay
    createOverlay();
    
    // Fetch and display score
    try {
      const data = await analyzeVideo(window.location.href);
      updateOverlay(data);
    } catch (error) {
      console.error('ViewMagnet: Analysis error', error);
      updateOverlayError();
    }
  }
  
  async function analyzeVideo(url) {
    const response = await fetch(`${API_BASE}/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ url }),
    });
    
    if (!response.ok) {
      throw new Error('API error');
    }
    
    return response.json();
  }
  
  function createOverlay() {
    scoreOverlay = document.createElement('div');
    scoreOverlay.id = 'ViewMagnet-overlay';
    scoreOverlay.className = 'ViewMagnet-overlay ViewMagnet-loading';
    scoreOverlay.innerHTML = `
      <div class="ViewMagnet-badge">
        <span class="ViewMagnet-icon">🎬</span>
        <span class="ViewMagnet-score">...</span>
      </div>
      <div class="ViewMagnet-tooltip">
        <div class="ViewMagnet-tooltip-content">
          <div class="ViewMagnet-loading-text">Analyzing...</div>
        </div>
      </div>
    `;
    
    // Insert near the video title
    const titleContainer = document.querySelector('#above-the-fold, #info-contents');
    if (titleContainer) {
      titleContainer.insertBefore(scoreOverlay, titleContainer.firstChild);
    }
  }
  
  function updateOverlay(data) {
    if (!scoreOverlay) return;
    
    const score = Math.round(data.prediction_score || 0);
    const tier = (data.prediction_tier || 'medium').toLowerCase();
    
    scoreOverlay.className = `ViewMagnet-overlay ViewMagnet-${tier}`;
    
    const scoreEl = scoreOverlay.querySelector('.ViewMagnet-score');
    if (scoreEl) {
      scoreEl.textContent = score;
    }
    
    const tooltipContent = scoreOverlay.querySelector('.ViewMagnet-tooltip-content');
    if (tooltipContent) {
      const explanations = (data.explanations || [])
        .slice(0, 2)
        .map(e => `${e.direction === 'positive' ? '✅' : '⚠️'} ${e.feature}`)
        .join('<br>');
      
      tooltipContent.innerHTML = `
        <div class="ViewMagnet-tier">${getTierEmoji(tier)} ${tier.toUpperCase()}</div>
        <div class="ViewMagnet-components">
          <span>📝 ${Math.round(data.title_score || 0)}</span>
          <span>🖼️ ${Math.round(data.thumbnail_score || 0)}</span>
          <span>📺 ${Math.round(data.channel_score || 0)}</span>
        </div>
        <div class="ViewMagnet-factors">${explanations || 'No specific factors'}</div>
        <div class="ViewMagnet-cta">Click for full analysis</div>
      `;
    }
    
    // Add click handler
    scoreOverlay.addEventListener('click', () => {
      chrome.runtime.sendMessage({ action: 'openPopup' });
    });
  }
  
  function updateOverlayError() {
    if (!scoreOverlay) return;
    
    scoreOverlay.className = 'ViewMagnet-overlay ViewMagnet-error';
    
    const scoreEl = scoreOverlay.querySelector('.ViewMagnet-score');
    if (scoreEl) {
      scoreEl.textContent = '?';
    }
    
    const tooltipContent = scoreOverlay.querySelector('.ViewMagnet-tooltip-content');
    if (tooltipContent) {
      tooltipContent.innerHTML = `
        <div class="ViewMagnet-error-text">Could not analyze video</div>
        <div class="ViewMagnet-cta">Make sure ViewMagnet API is running</div>
      `;
    }
  }
  
  function removeOverlay() {
    if (scoreOverlay) {
      scoreOverlay.remove();
      scoreOverlay = null;
    }
  }
  
  function getTierEmoji(tier) {
    const emojis = {
      viral: '🔥',
      high: '✅',
      medium: '🟡',
      low: '⚠️'
    };
    return emojis[tier] || '❓';
  }
  
  function waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
      const element = document.querySelector(selector);
      if (element) {
        return resolve(element);
      }
      
      const observer = new MutationObserver(() => {
        const element = document.querySelector(selector);
        if (element) {
          observer.disconnect();
          resolve(element);
        }
      });
      
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
      
      setTimeout(() => {
        observer.disconnect();
        reject(new Error('Element not found: ' + selector));
      }, timeout);
    });
  }
})();




