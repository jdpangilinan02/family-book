/* Family Book — D3 Tree Visualization */

(function() {
  'use strict';

  var svg, g, zoom, treeData;
  var NODE_RADIUS = 30;
  var NODE_SPACING_X = 100;
  var NODE_SPACING_Y = 140;

  // Read config from template (supports demo mode)
  var config = window.TREE_CONFIG || {};
  var API_URL = config.apiUrl || '/api/tree';
  var PERSON_BASE_URL = config.personBaseUrl || '/people';
  var IS_DEMO = config.demoMode || false;

  // Fetch tree data and render
  async function init() {
    try {
      var resp = await fetch(API_URL);
      if (resp.status === 401) {
        window.location.href = '/login';
        return;
      }
      treeData = await resp.json();
      render();
    } catch(err) {
      document.getElementById('tree-page').textContent = 'Failed to load tree data.';
    }
  }

  function render() {
    var container = document.getElementById('tree-page');
    var w = container.clientWidth;
    var h = container.clientHeight;

    svg = d3.select('#tree-svg')
      .attr('width', w)
      .attr('height', h);

    // Clear any previous render
    svg.selectAll('*').remove();

    g = svg.append('g');

    zoom = d3.zoom()
      .scaleExtent([0.2, 3])
      .on('zoom', function(event) {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    if (!treeData || !treeData.persons || treeData.persons.length === 0) {
      g.append('text')
        .attr('x', w / 2).attr('y', h / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#6b6054')
        .text('No family members yet');
      return;
    }

    // Build data structures
    var personsById = {};
    treeData.persons.forEach(function(p) { personsById[p.id] = p; });

    // Build hierarchy from parent-child relationships
    var childToParents = {};
    var parentToChildren = {};
    treeData.parent_child.forEach(function(pc) {
      if (!childToParents[pc.child_id]) childToParents[pc.child_id] = [];
      childToParents[pc.child_id].push(pc.parent_id);
      if (!parentToChildren[pc.parent_id]) parentToChildren[pc.parent_id] = [];
      parentToChildren[pc.parent_id].push(pc.child_id);
    });

    // Build partnership lookup
    var partnerMap = {};
    treeData.partnerships.forEach(function(p) {
      if (!partnerMap[p.person_a_id]) partnerMap[p.person_a_id] = [];
      partnerMap[p.person_a_id].push(p);
      if (!partnerMap[p.person_b_id]) partnerMap[p.person_b_id] = [];
      partnerMap[p.person_b_id].push(p);
    });

    // Find root
    var rootId = treeData.root_id;
    if (!rootId || !personsById[rootId]) {
      var allChildIds = new Set(Object.keys(childToParents));
      var rootCandidates = treeData.persons.filter(function(p) { return !allChildIds.has(p.id); });
      rootId = rootCandidates.length > 0 ? rootCandidates[0].id : treeData.persons[0].id;
    }

    // Build tree hierarchy using BFS from root
    var visited = new Set();
    var nodePositions = {};

    function buildHierarchy(rootId) {
      var root = {id: rootId, children: [], depth: 0, x: 0, y: 0};
      var queue = [root];
      visited.add(rootId);

      while (queue.length > 0) {
        var node = queue.shift();
        var children = parentToChildren[node.id] || [];
        children.forEach(function(cid) {
          if (visited.has(cid)) return;
          visited.add(cid);
          var child = {id: cid, children: [], depth: node.depth + 1, parent: node};
          node.children.push(child);
          queue.push(child);
        });
      }
      return root;
    }

    var rootNode = buildHierarchy(rootId);

    // Layout using simple recursive positioning
    var maxDepth = 0;

    function layoutTree(node, xStart, y) {
      node.y = y;
      if (node.depth > maxDepth) maxDepth = node.depth;

      if (node.children.length === 0) {
        node.x = xStart + NODE_SPACING_X / 2;
        return xStart + NODE_SPACING_X;
      }

      var x = xStart;
      node.children.forEach(function(child) {
        x = layoutTree(child, x, y + NODE_SPACING_Y);
      });

      var first = node.children[0];
      var last = node.children[node.children.length - 1];
      node.x = (first.x + last.x) / 2;

      return x;
    }

    layoutTree(rootNode, 0, 60);

    // Collect all nodes
    var allNodes = [];
    function collectNodes(node) {
      allNodes.push(node);
      nodePositions[node.id] = {x: node.x, y: node.y};
      node.children.forEach(collectNodes);
    }
    collectNodes(rootNode);

    // Add unvisited persons at the bottom
    var unvisited = treeData.persons.filter(function(p) { return !visited.has(p.id); });
    var ux = 0;
    unvisited.forEach(function(p) {
      var node = {id: p.id, children: [], depth: maxDepth + 1, x: ux, y: (maxDepth + 1) * NODE_SPACING_Y + 60};
      allNodes.push(node);
      nodePositions[p.id] = {x: node.x, y: node.y};
      ux += NODE_SPACING_X;
    });

    // Draw parent-child lines
    var lineGen = d3.line().curve(d3.curveBumpY);

    allNodes.forEach(function(node) {
      if (node.children) {
        node.children.forEach(function(child) {
          g.append('path')
            .attr('class', 'parent-child-line')
            .attr('d', lineGen([[node.x, node.y + NODE_RADIUS], [child.x, child.y - NODE_RADIUS]]));
        });
      }
    });

    // Draw partnership lines
    treeData.partnerships.forEach(function(p) {
      var posA = nodePositions[p.person_a_id];
      var posB = nodePositions[p.person_b_id];
      if (!posA || !posB) return;
      var dissolved = p.status === 'dissolved' || p.status === 'separated';
      g.append('line')
        .attr('class', 'partnership-line' + (dissolved ? ' partnership-line--dissolved' : ''))
        .attr('x1', posA.x).attr('y1', posA.y)
        .attr('x2', posB.x).attr('y2', posB.y);
    });

    // Draw person nodes
    allNodes.forEach(function(node) {
      var person = personsById[node.id];
      if (!person) return;

      var nodeG = g.append('g')
        .attr('class', 'person-node' + (person.branch ? ' person-node--branch-' + person.branch : ''))
        .attr('data-id', person.id)
        .attr('transform', 'translate(' + node.x + ',' + node.y + ')')
        .style('cursor', 'pointer');

      // Photo circle
      if (person.photo_url) {
        var clipId = 'clip-' + person.id.replace(/[^a-zA-Z0-9]/g, '');
        var defs = nodeG.append('defs');
        defs.append('clipPath').attr('id', clipId)
          .append('circle').attr('r', NODE_RADIUS);
        var photoSrc = person.photo_url.startsWith('http')
          ? person.photo_url
          : '/api/media/' + person.photo_url + '/file';
        nodeG.append('image')
          .attr('href', photoSrc)
          .attr('x', -NODE_RADIUS).attr('y', -NODE_RADIUS)
          .attr('width', NODE_RADIUS * 2).attr('height', NODE_RADIUS * 2)
          .attr('clip-path', 'url(#' + clipId + ')')
          .attr('preserveAspectRatio', 'xMidYMid slice');
        nodeG.append('circle')
          .attr('class', 'photo-clip')
          .attr('r', NODE_RADIUS)
          .attr('fill', 'none')
          .attr('stroke', 'white').attr('stroke-width', 2);
      } else {
        nodeG.append('circle')
          .attr('class', 'photo-clip')
          .attr('r', NODE_RADIUS);
        nodeG.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('fill', '#2d5016').attr('font-size', '14px').attr('font-weight', '600')
          .attr('pointer-events', 'none')
          .text(person.display_name.substring(0, 2));
      }

      // Larger tap target for mobile
      nodeG.append('circle')
        .attr('class', 'tap-target')
        .attr('r', NODE_RADIUS + 10);

      // Name label
      nodeG.append('text')
        .attr('class', 'name-label')
        .attr('dy', NODE_RADIUS + 16)
        .text(person.display_name);

      // Country flag
      if (person.residence_country_code) {
        nodeG.append('text')
          .attr('class', 'rel-label')
          .attr('dy', NODE_RADIUS + 30)
          .text(countryFlag(person.residence_country_code));
      }

      // Click handler — load person card into sidebar via HTMX
      nodeG.on('click', function() {
        openPersonSidebar(person.id);
      });

      // Double-click — navigate to profile
      nodeG.on('dblclick', function() {
        window.location.href = PERSON_BASE_URL + '/' + person.id;
      });
    });

    // Center the tree
    var bounds = g.node().getBBox();
    var dx = w / 2 - (bounds.x + bounds.width / 2);
    var dy = h / 2 - (bounds.y + bounds.height / 2);
    var scale = Math.min(w / (bounds.width + 100), h / (bounds.height + 100), 1);
    svg.call(zoom.transform,
      d3.zoomIdentity.translate(dx, dy).scale(scale));
  }

  // Open person sidebar using HTMX
  function openPersonSidebar(personId) {
    var sidebar = document.getElementById('person-sidebar');
    var content = document.getElementById('sidebar-content');
    sidebar.classList.add('person-sidebar--open');
    // Use HTMX to safely load server-rendered HTML
    htmx.ajax('GET', PERSON_BASE_URL + '/' + personId + '/card', {target: '#sidebar-content', swap: 'innerHTML'});
  }

  // Country code to flag emoji
  function countryFlag(code) {
    if (!code || code.length !== 2) return '';
    var OFFSET = 127397;
    return String.fromCodePoint(code.charCodeAt(0) + OFFSET, code.charCodeAt(1) + OFFSET);
  }

  // Zoom controls
  window.treeZoomIn = function() { svg.transition().call(zoom.scaleBy, 1.3); };
  window.treeZoomOut = function() { svg.transition().call(zoom.scaleBy, 0.7); };
  window.treeReset = function() { render(); };
  window.closeSidebar = function() {
    document.getElementById('person-sidebar').classList.remove('person-sidebar--open');
  };

  // Handle resize
  var resizeTimeout;
  window.addEventListener('resize', function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function() {
      if (treeData) render();
    }, 250);
  });

  // Init on load
  init();
})();
