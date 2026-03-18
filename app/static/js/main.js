/* Family Book — main.js */

// Nav toggle (mobile)
function toggleNav() {
  document.getElementById('nav-links').classList.toggle('nav__links--open');
}
// Close nav on link click (mobile)
document.addEventListener('click', function(e) {
  var links = document.getElementById('nav-links');
  if (links && !e.target.closest('.nav__hamburger') && !e.target.closest('#nav-links')) {
    links.classList.remove('nav__links--open');
  }
});

// Logout
async function logout() {
  await fetch('/auth/logout', {method: 'POST'});
  window.location.href = '/login';
}

// Toast
function showToast(msg) {
  var container = document.getElementById('toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 3000);
}

// Check URL for toast param
(function() {
  var params = new URLSearchParams(window.location.search);
  if (params.get('toast')) {
    showToast(params.get('toast'));
    params.delete('toast');
    var newUrl = window.location.pathname;
    if (params.toString()) newUrl += '?' + params.toString();
    history.replaceState(null, '', newUrl);
  }
})();

// Reaction picker toggle
function toggleReactionPicker(momentId) {
  var el = document.getElementById('reaction-picker-' + momentId);
  if (el) el.classList.toggle('hidden');
}

// Comments toggle
function toggleComments(momentId) {
  var el = document.getElementById('comments-' + momentId);
  if (el) {
    el.classList.toggle('hidden');
    if (!el.classList.contains('hidden') && !el.dataset.loaded) {
      el.dataset.loaded = '1';
      htmx.trigger(el, 'toggle-comments-' + momentId);
    }
  }
}

// Post comment
async function postComment(e, momentId) {
  e.preventDefault();
  var input = e.target.querySelector('input[name="body"]');
  var body = input.value.trim();
  if (!body) return;
  input.disabled = true;
  try {
    var resp = await fetch('/api/moments/' + momentId + '/comments', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({body: body})
    });
    if (resp.ok) {
      input.value = '';
      // Reload comments
      htmx.ajax('GET', '/partials/comments/' + momentId, '#comments-' + momentId);
    }
  } finally {
    input.disabled = false;
  }
}

// Lightbox
function openLightbox(url) {
  var lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.onclick = function() { lb.remove(); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'lightbox__close';
  closeBtn.textContent = '\u00D7';
  closeBtn.onclick = function(e) { e.stopPropagation(); lb.remove(); };
  var img = document.createElement('img');
  img.src = url;
  img.alt = '';
  lb.appendChild(closeBtn);
  lb.appendChild(img);
  document.body.appendChild(lb);
}

// Media upload (person profile page)
async function uploadMedia() {
  var fileInput = document.getElementById('media-upload-file');
  if (!fileInput || !fileInput.files[0]) return showToast('Select a file');
  var fd = new FormData();
  fd.append('file', fileInput.files[0]);
  // Get person_id from URL
  var match = window.location.pathname.match(/\/people\/([^/]+)/);
  if (match) fd.append('person_id', match[1]);
  var resp = await fetch('/api/media', {method: 'POST', body: fd});
  if (resp.ok) {
    showToast('Uploaded');
    window.location.reload();
  } else {
    showToast('Upload failed');
  }
}

// Person sidebar (tree page)
function closeSidebar() {
  var el = document.getElementById('person-sidebar');
  if (el) el.classList.remove('person-sidebar--open');
}
