// ViewMagnet Chrome Extension Popup Script

const API_BASE = 'http://localhost:8000';

// DOM Elements
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const errorMessageEl = document.getElementById('error-message');
const notYoutubeEl = document.getElementById('not-youtube');
const resultsEl = document.getElementById('results');
const retryBtn = document.getElementById('retry-btn');
const analyzeBtn = document.getElementById('analyze-btn');
const manualUrlInput = document.getElementById('manual-url');
const openFullBtn = document.getElementById('open-full');

// State
let currentVideoUrl = null;

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
  // Check if we're on YouTube
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  if (tab && tab.url && isYouTubeVideo(tab.url)) {
    currentVideoUrl = tab.url;
    analyzeVideo(tab.url);
  } else {
    showNotYoutube();
  }
  
  // Event listeners
  retryBtn.addEventListener('click', () => {
    if (currentVideoUrl) {
      analyzeVideo(currentVideoUrl);
    }
  });
  
  analyzeBtn.addEventListener('click', () => {
    const url = manualUrlInput.value.trim();
    if (url && isYouTubeVideo(url)) {
      currentVideoUrl = url;
      analyzeVideo(url);
    } else {
      showError('Please enter a valid YouTube URL');
    }
  });
  
  manualUrlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      analyzeBtn.click();
    }
  });
  
  openFullBtn.addEventListener('click', () => {
    chrome.tabs.create({ url: 'http://localhost:8502' });
  });
}

function isYouTubeVideo(url) {
  return url.includes('youtube.com/watch') || url.includes('youtu.be/');
}

async function analyzeVideo(url) {
  showLoading();
  
  try {
    const response = await fetch(`${API_BASE}/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ url }),
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    
    const data = await response.json();
    
    if (data.error) {
      throw new Error(data.error);
    }
    
    showResults(data);
  } catch (error) {
    console.error('Analysis error:', error);
    
    // If API is not available, try direct analysis message
    if (error.message.includes('fetch') || error.message.includes('network')) {
      showError('Cannot connect to ViewMagnet API. Make sure the server is running on localhost:8000');
    } else {
      showError(error.message);
    }
  }
}

function showLoading() {
  hideAll();
  loadingEl.classList.remove('hidden');
}

function showError(message) {
  hideAll();
  errorMessageEl.textContent = message;
  errorEl.classList.remove('hidden');
}

function showNotYoutube() {
  hideAll();
  notYoutubeEl.classList.remove('hidden');
}

function showResults(data) {
  hideAll();
  
  // Score
  const scoreEl = document.getElementById('score');
  const tierEl = document.getElementById('tier');
  const titleEl = document.getElementById('title');
  
  const score = Math.round(data.prediction_score || 0);
  scoreEl.textContent = score;
  scoreEl.className = 'score ' + getScoreClass(score);
  
  const tier = (data.prediction_tier || 'medium').toLowerCase();
  tierEl.textContent = getTierEmoji(tier) + ' ' + tier.toUpperCase();
  tierEl.className = 'tier ' + tier;
  
  titleEl.textContent = data.title || 'Unknown Video';
  
  // Component scores
  document.getElementById('title-score').textContent = Math.round(data.title_score || 0);
  document.getElementById('thumb-score').textContent = Math.round(data.thumbnail_score || 0);
  document.getElementById('channel-score').textContent = Math.round(data.channel_score || 0);
  
  // Factors
  const factorsEl = document.getElementById('factors');
  factorsEl.innerHTML = '';
  
  const explanations = data.explanations || [];
  explanations.slice(0, 3).forEach(exp => {
    const div = document.createElement('div');
    const isPositive = exp.direction === 'positive';
    div.className = 'factor ' + (isPositive ? 'positive' : 'negative');
    div.innerHTML = `
      <span class="factor-label">${isPositive ? '✅' : '⚠️'} ${exp.feature}</span>
      <span class="factor-desc">${exp.impact}</span>
    `;
    factorsEl.appendChild(div);
  });
  
  if (explanations.length === 0) {
    factorsEl.innerHTML = '<div class="factor positive"><span class="factor-label">Analysis complete</span></div>';
  }
  
  // Recommendations
  const recsEl = document.getElementById('recommendations');
  recsEl.innerHTML = '';
  
  const recommendations = data.recommendations || [];
  recommendations.slice(0, 3).forEach(rec => {
    const div = document.createElement('div');
    div.className = 'recommendation';
    div.textContent = '💎 ' + rec;
    recsEl.appendChild(div);
  });
  
  if (recommendations.length === 0) {
    recsEl.innerHTML = '<div class="recommendation">✨ Looking good! No major improvements needed.</div>';
  }
  
  resultsEl.classList.remove('hidden');
}

function hideAll() {
  loadingEl.classList.add('hidden');
  errorEl.classList.add('hidden');
  notYoutubeEl.classList.add('hidden');
  resultsEl.classList.add('hidden');
}

function getScoreClass(score) {
  if (score >= 80) return 'score-viral';
  if (score >= 65) return 'score-high';
  if (score >= 45) return 'score-medium';
  return 'score-low';
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




