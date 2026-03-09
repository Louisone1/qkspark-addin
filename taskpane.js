var allIssues = [];
var issueStates = {}; // idx -> 'pending' | 'accepted' | 'ignored'
var currentFilter = 'all';
var lastParagraphs = [];
var ANCHOR_WINDOW = 16;

Office.onReady(function(info) {
  if (info.host === Office.HostType.Word) {
    showStatus('✅ Word 已连接', 'ok');
    setTimeout(function() { hideStatus(); }, 2000);
  }
});

function getApiBase() {
  var v = document.getElementById('apiUrl').value.trim();
  return v ? v.replace(/\/+$/, '') : '';
}

function showStatus(msg, type) {
  var el = document.getElementById('statusBar');
  el.textContent = msg;
  el.className = 'status-bar show ' + (type || '');
}
function hideStatus() {
  document.getElementById('statusBar').className = 'status-bar';
}

function startProofread() {
  var btn = document.getElementById('btnProofread');
  btn.disabled = true;
  btn.textContent = '编校中...';
  showStatus('正在读取文档...', 'loading');

  Word.run(function(ctx) {
    var paragraphs = ctx.document.body.paragraphs;
    paragraphs.load('text');
    return ctx.sync().then(function() {
      var items = [];
      for (var i = 0; i < paragraphs.items.length; i++) {
        var t = paragraphs.items[i].text.trim();
        if (t.length > 0) {
          items.push({ index: i, text: t });
        }
      }
      lastParagraphs = items.slice();
      return callProofread(items);
    });
  }).catch(function(err) {
    showStatus('❌ 读取文档失败: ' + err.message, 'err');
    btn.disabled = false;
    btn.textContent = '开始编校';
  });
}

function callProofread(paragraphs) {
  var btn = document.getElementById('btnProofread');
  var pw = document.getElementById('progressWrap');
  var pf = document.getElementById('progressFill');
  var pt = document.getElementById('progressText');
  pw.className = 'progress-wrap show';

  var batchSize = 10;
  var batches = [];
  for (var i = 0; i < paragraphs.length; i += batchSize) {
    batches.push(paragraphs.slice(i, i + batchSize));
  }

  allIssues = [];
  issueStates = {};
  var done = 0;

  function nextBatch(idx) {
    if (idx >= batches.length) {
      pf.style.width = '100%';
      pt.textContent = '编校完成';
      btn.disabled = false;
      btn.textContent = '开始编校';
      showStatus('✅ 编校完成，共发现 ' + allIssues.length + ' 处问题', 'ok');
      renderResults();
      return;
    }
    pt.textContent = '编校中... 批次 ' + (idx + 1) + '/' + batches.length;
    pf.style.width = ((idx + 1) / batches.length * 100) + '%';

    fetch(getApiBase() + '/api/proofread', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paragraphs: batches[idx] })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.issues) {
        data.issues.forEach(function(iss) {
          var enriched = enrichIssueAnchors(iss, paragraphs);
          var gIdx = allIssues.length;
          issueStates[gIdx] = 'pending';
          allIssues.push(enriched);
        });
      }
      nextBatch(idx + 1);
    })
    .catch(function(err) {
      showStatus('❌ 编校失败: ' + err.message, 'err');
      btn.disabled = false;
      btn.textContent = '开始编校';
    });
  }

  nextBatch(0);
}

function renderResults() {
  var rc = document.getElementById('resultCard');
  rc.style.display = 'block';

  var counts = { error: 0, warning: 0, info: 0 };
  allIssues.forEach(function(iss) {
    var s = iss.severity || 'info';
    counts[s] = (counts[s] || 0) + 1;
  });

  var sb = document.getElementById('statsBar');
  sb.innerHTML =
    '<span class="stat-badge stat-error' + (currentFilter === 'error' ? ' active' : '') + '" onclick="filterBy(\'error\')">🔴 错误 ' + counts.error + '</span>' +
    '<span class="stat-badge stat-warning' + (currentFilter === 'warning' ? ' active' : '') + '" onclick="filterBy(\'warning\')">🟡 存疑 ' + counts.warning + '</span>' +
    '<span class="stat-badge stat-info' + (currentFilter === 'info' ? ' active' : '') + '" onclick="filterBy(\'info\')">🔵 建议 ' + counts.info + '</span>' +
    '<span class="stat-badge' + (currentFilter === 'all' ? ' active' : '') + '" onclick="filterBy(\'all\')">全部 ' + allIssues.length + '</span>';

  document.getElementById('batchActions').style.display = allIssues.length > 0 ? 'flex' : 'none';

  updateSummary();
  renderIssueList();
}

function updateSummary() {
  var accepted = 0, ignored = 0, pending = 0;
  for (var k in issueStates) {
    if (issueStates[k] === 'accepted') accepted++;
    else if (issueStates[k] === 'ignored') ignored++;
    else pending++;
  }
  var bar = document.getElementById('summaryBar');
  if (accepted > 0 || ignored > 0) {
    bar.style.display = 'flex';
    bar.innerHTML =
      '<span>✅ 已修复 ' + accepted + '</span>' +
      '<span>⊘ 已忽略 ' + ignored + '</span>' +
      '<span>⏳ 待处理 ' + pending + '</span>';
  } else {
    bar.style.display = 'none';
  }
}

function renderIssueList() {
  var list = document.getElementById('issueList');
  var catLabels = {
    spelling: '错别字', grammar: '语病', punctuation: '标点',
    terminology: '术语', consistency: '一致性', expression: '表达'
  };
  var catClass = {
    spelling: 'cat-spelling', grammar: 'cat-grammar', punctuation: 'cat-punctuation',
    terminology: 'cat-terminology', consistency: 'cat-consistency', expression: 'cat-expression'
  };

  var html = '';
  allIssues.forEach(function(iss, idx) {
    if (currentFilter !== 'all' && iss.severity !== currentFilter) return;

    var state = issueStates[idx] || 'pending';
    var resolved = state !== 'pending';
    var sevClass = 'sev-' + (iss.severity || 'info');

    html += '<div class="issue-item' + (resolved ? ' resolved' : '') + '" id="issue-' + idx + '">';
    html += '<div class="issue-header">';
    html += '<div><span class="issue-cat ' + (catClass[iss.category] || 'cat-expression') + '">' + (catLabels[iss.category] || iss.category) + '</span></div>';
    html += '<span class="issue-para">¶' + (iss.paragraph_index + 1) + '</span>';
    html += '</div>';

    html += '<div class="issue-content">';
    html += '<span class="issue-sev ' + sevClass + '"></span>';
    html += '<span class="issue-original">' + esc(iss.original) + '</span>';
    html += '<span class="issue-arrow">→</span>';
    html += '<span class="issue-suggestion">' + esc(iss.suggestion) + '</span>';
    html += '</div>';

    html += '<div class="issue-reason">' + esc(iss.reason) + '</div>';

    if (state === 'accepted') {
      html += '<span class="issue-status status-accepted">✅ 已修复</span>';
    } else if (state === 'ignored') {
      html += '<span class="issue-status status-ignored">⊘ 已忽略</span>';
      html += ' <button class="btn btn-sm btn-ghost" style="margin-top:4px" onclick="undoIssue(' + idx + ')">↩ 撤销</button>';
    } else {
      html += '<div class="issue-actions">';
      html += '<button class="btn btn-sm btn-success" onclick="acceptIssue(' + idx + ')">✅ 采纳</button>';
      html += '<button class="btn btn-sm btn-danger" onclick="ignoreIssue(' + idx + ')">⊘ 忽略</button>';
      html += '<button class="btn btn-sm btn-ghost" onclick="locateIssue(' + idx + ')">📍 定位</button>';
      html += '</div>';
    }

    html += '</div>';
  });

  list.innerHTML = html || '<div style="text-align:center;color:var(--muted);padding:20px">🎉 没有发现问题</div>';
}

function filterBy(type) {
  currentFilter = type;
  renderResults();
}

function getParagraphTextByIndex(paragraphIndex) {
  for (var i = 0; i < lastParagraphs.length; i++) {
    if (lastParagraphs[i].index === paragraphIndex) return lastParagraphs[i].text || '';
  }
  return '';
}

function enrichIssueAnchors(iss, paragraphs) {
  var out = {};
  for (var k in iss) out[k] = iss[k];

  var paragraphText = '';
  if (typeof iss.paragraph_index === 'number') {
    for (var i = 0; i < paragraphs.length; i++) {
      if (paragraphs[i].index === iss.paragraph_index) {
        paragraphText = paragraphs[i].text || '';
        break;
      }
    }
  }
  out.paragraph_excerpt = paragraphText ? paragraphText.slice(0, 120) : (iss.paragraph_excerpt || '');

  if (!out.anchor_prefix || !out.anchor_suffix) {
    var original = iss.original || '';
    var pos = paragraphText.indexOf(original);
    if (paragraphText && original && pos >= 0) {
      out.anchor_prefix = paragraphText.slice(Math.max(0, pos - ANCHOR_WINDOW), pos);
      out.anchor_suffix = paragraphText.slice(pos + original.length, pos + original.length + ANCHOR_WINDOW);
    } else {
      out.anchor_prefix = out.anchor_prefix || '';
      out.anchor_suffix = out.anchor_suffix || '';
    }
  }

  return out;
}

function scoreAnchorMatch(text, original, prefix, suffix) {
  var candidates = [];
  if (!text || !original) return candidates;
  var start = 0;
  while (true) {
    var idx = text.indexOf(original, start);
    if (idx < 0) break;
    var before = text.slice(Math.max(0, idx - (prefix || '').length), idx);
    var after = text.slice(idx + original.length, idx + original.length + (suffix || '').length);
    var score = 0;
    if (prefix && before === prefix) score += 2;
    else if (prefix && prefix.length > 0 && before && prefix.indexOf(before) >= 0) score += 1;
    if (suffix && after === suffix) score += 2;
    else if (suffix && suffix.length > 0 && after && suffix.indexOf(after) >= 0) score += 1;
    candidates.push({ index: idx, score: score, before: before, after: after });
    start = idx + original.length;
  }
  return candidates;
}

function findBestAnchoredRange(ctx, paragraphs, iss) {
  var original = iss.original || '';
  var prefix = iss.anchor_prefix || '';
  var suffix = iss.anchor_suffix || '';
  var targetParagraph = typeof iss.paragraph_index === 'number' ? iss.paragraph_index : -1;
  var paragraphCandidates = [];

  for (var i = 0; i < paragraphs.items.length; i++) {
    var p = paragraphs.items[i];
    if (!p.text || p.text.indexOf(original) < 0) continue;
    if (targetParagraph >= 0 && Math.abs(i - targetParagraph) > 1) continue;
    var scored = scoreAnchorMatch(p.text, original, prefix, suffix);
    if (scored.length === 0) continue;
    scored.sort(function(a, b) { return b.score - a.score; });
    paragraphCandidates.push({ paragraph: p, paragraphIndex: i, best: scored[0], all: scored });
  }

  if (paragraphCandidates.length === 0 && targetParagraph < 0) {
    for (var j = 0; j < paragraphs.items.length; j++) {
      var p2 = paragraphs.items[j];
      if (!p2.text || p2.text.indexOf(original) < 0) continue;
      var scored2 = scoreAnchorMatch(p2.text, original, prefix, suffix);
      if (scored2.length === 0) continue;
      scored2.sort(function(a, b) { return b.score - a.score; });
      paragraphCandidates.push({ paragraph: p2, paragraphIndex: j, best: scored2[0], all: scored2 });
    }
  }

  if (paragraphCandidates.length === 0) return null;
  paragraphCandidates.sort(function(a, b) {
    if (b.best.score !== a.best.score) return b.best.score - a.best.score;
    if (targetParagraph >= 0) return Math.abs(a.paragraphIndex - targetParagraph) - Math.abs(b.paragraphIndex - targetParagraph);
    return a.paragraphIndex - b.paragraphIndex;
  });

  var winner = paragraphCandidates[0];
  var ambiguous = paragraphCandidates.length > 1 && paragraphCandidates[1].best.score === winner.best.score;
  if (ambiguous && winner.best.score < 4) return { ambiguous: true, paragraphIndex: winner.paragraphIndex };

  var ranges = winner.paragraph.search(original, { matchCase: false, matchWholeWord: false });
  ranges.load('text');
  return { paragraphIndex: winner.paragraphIndex, ranges: ranges, score: winner.best.score };
}

function acceptIssue(idx) {
  var iss = allIssues[idx];
  if (!iss || !iss.original || !iss.suggestion) {
    showStatus('❌ 该问题缺少替换信息', 'err');
    return;
  }

  Word.run(function(ctx) {
    var paragraphs = ctx.document.body.paragraphs;
    paragraphs.load('text');
    return ctx.sync().then(function() {
      var located = findBestAnchoredRange(ctx, paragraphs, iss);
      if (!located) {
        showStatus('⚠️ 未找到可安全替换的位置：' + iss.original, 'err');
        return;
      }
      if (located.ambiguous) {
        showStatus('⚠️ 该问题定位不唯一，请先点击“定位”确认后再手动处理', 'err');
        return;
      }
      return ctx.sync().then(function() {
        if (located.ranges.items.length > 0) {
          located.ranges.items[0].insertText(iss.suggestion, 'Replace');
          return ctx.sync().then(function() {
            issueStates[idx] = 'accepted';
            renderResults();
            showStatus('✅ 已按双锚定替换: ' + iss.original + ' → ' + iss.suggestion, 'ok');
          });
        }
        showStatus('⚠️ 找到段落但未命中文本：' + iss.original, 'err');
      });
    });
  }).catch(function(err) {
    showStatus('❌ 替换失败: ' + err.message, 'err');
  });
}

function ignoreIssue(idx) {
  issueStates[idx] = 'ignored';
  renderResults();
}

function undoIssue(idx) {
  issueStates[idx] = 'pending';
  renderResults();
}

function locateIssue(idx) {
  var iss = allIssues[idx];
  Word.run(function(ctx) {
    var paragraphs = ctx.document.body.paragraphs;
    paragraphs.load('text');
    return ctx.sync().then(function() {
      if (iss.original) {
        var located = findBestAnchoredRange(ctx, paragraphs, iss);
        if (located && !located.ambiguous) {
          return ctx.sync().then(function() {
            if (located.ranges.items.length > 0) {
              located.ranges.items[0].select();
              return ctx.sync();
            }
          });
        }
      }
      var pIdx = iss.paragraph_index;
      if (pIdx >= 0 && pIdx < paragraphs.items.length) {
        paragraphs.items[pIdx].select();
        return ctx.sync();
      }
    });
  }).catch(function(err) {
    showStatus('❌ 定位失败: ' + err.message, 'err');
  });
}

function batchAcceptAll() {
  var toAccept = [];
  allIssues.forEach(function(iss, idx) {
    if (issueStates[idx] !== 'pending') return;
    if (iss.original && iss.suggestion) toAccept.push(idx);
  });

  if (toAccept.length === 0) {
    showStatus('没有可采纳的问题', 'ok');
    return;
  }

  if (!confirm('确认全部采纳（共 ' + toAccept.length + ' 处）？将直接修改文档内容。')) return;

  showStatus('正在批量替换...', 'loading');

  Word.run(function(ctx) {
    var paragraphs = ctx.document.body.paragraphs;
    paragraphs.load('text');
    return ctx.sync().then(function() {
      var plans = [];
      var skipped = 0;

      toAccept.forEach(function(idx) {
        var iss = allIssues[idx];
        var located = findBestAnchoredRange(ctx, paragraphs, iss);
        if (!located || located.ambiguous) {
          skipped++;
          return;
        }
        plans.push({ idx: idx, iss: iss, ranges: located.ranges, paragraphIndex: located.paragraphIndex });
      });

      return ctx.sync().then(function() {
        plans.sort(function(a, b) {
          if (a.paragraphIndex !== b.paragraphIndex) return b.paragraphIndex - a.paragraphIndex;
          return 0;
        });

        var replaced = 0;
        plans.forEach(function(p) {
          if (p.ranges.items.length > 0) {
            p.ranges.items[0].insertText(p.iss.suggestion, 'Replace');
            issueStates[p.idx] = 'accepted';
            replaced++;
          } else {
            skipped++;
          }
        });

        return ctx.sync().then(function() {
          renderResults();
          showStatus('✅ 已按双锚定替换 ' + replaced + ' 处，跳过 ' + skipped + ' 处不确定项', 'ok');
        });
      });
    });
  }).catch(function(err) {
    showStatus('❌ 批量替换失败: ' + err.message, 'err');
  });
}

function batchIgnoreAll() {
  var toIgnore = 0;
  allIssues.forEach(function(iss, idx) {
    if (issueStates[idx] === 'pending') {
      issueStates[idx] = 'ignored';
      toIgnore++;
    }
  });
  renderResults();
  showStatus('已忽略 ' + toIgnore + ' 处问题', 'ok');
}

function clearResults() {
  showStatus('正在清除文档中的报告...', 'loading');
  Word.run(function(ctx) {
    // 搜索报告分隔线
    var sepResults = ctx.document.body.search('————————————————————', { matchCase: true });
    sepResults.load('text');
    return ctx.sync().then(function() {
      if (sepResults.items.length === 0) {
        showStatus('文档中没有找到编校报告', 'ok');
        return;
      }
      // 取最后一个分隔线（最近一次导出的报告）
      var sepRange = sepResults.items[sepResults.items.length - 1];
      var endRange = ctx.document.body.getRange('End');
      var reportRange = sepRange.expandTo(endRange);
      reportRange.delete();
      return ctx.sync().then(function() {
        showStatus('✅ 已清除文档中的编校报告', 'ok');
      });
    });
  }).catch(function(err) {
    showStatus('❌ 清除失败: ' + err.message, 'err');
  });
}

function getRevisionMarkMode() {
  // 先走最稳模式：高亮 + 尾注；后续再接 native_comment / report_only 配置
  return 'highlight_note';
}

function getRevisionHighlightColor(severity) {
  if (severity === 'error') return 'Pink';
  if (severity === 'warning') return 'Yellow';
  return 'Turquoise';
}

function buildRevisionNote(iss) {
  var sevLabel = { error: '🔴', warning: '🟡', info: '🔵' };
  var parts = [];
  if (sevLabel[iss.severity]) parts.push(sevLabel[iss.severity]);
  if (iss.suggestion) parts.push('建议：' + iss.suggestion);
  if (iss.reason) parts.push('说明：' + iss.reason);
  return '【修订标记】' + parts.join(' | ');
}

function applyRevisionMark(range, iss, mode) {
  if (mode === 'native_comment') {
    range.insertComment(buildRevisionNote(iss));
    return 'native_comment';
  }

  if (mode === 'report_only') {
    return 'report_only';
  }

  range.font.highlightColor = getRevisionHighlightColor(iss.severity);
  var note = ' ' + buildRevisionNote(iss);
  var inserted = range.insertText(note, 'After');
  inserted.font.color = '#c00000';
  inserted.font.size = 8;
  inserted.font.italic = true;
  return 'highlight_note';
}

function writeComments() {
  var pending = [];
  allIssues.forEach(function(iss, idx) {
    if (issueStates[idx] === 'accepted') return;
    if (iss.original) pending.push(iss);
  });

  if (pending.length === 0) {
    showStatus('没有需要写入修订标记的问题', 'ok');
    return;
  }

  var mode = getRevisionMarkMode();
  var statusLabel = mode === 'native_comment' ? '原生批注' : (mode === 'report_only' ? '仅报告' : '高亮+尾注');
  showStatus('正在写入修订标记（' + statusLabel + '）...', 'loading');

  Word.run(function(ctx) {
    var searchPairs = [];
    pending.forEach(function(iss) {
      var sr = ctx.document.body.search(iss.original, { matchCase: false });
      sr.load('text');
      searchPairs.push({ sr: sr, iss: iss });
    });
    return ctx.sync().then(function() {
      var written = 0;
      var nativeCount = 0;
      var highlightCount = 0;
      var reportOnlyCount = 0;

      searchPairs.forEach(function(p) {
        if (p.sr.items.length > 0) {
          var range = p.sr.items[0];
          try {
            var applied = applyRevisionMark(range, p.iss, mode);
            if (applied === 'native_comment') nativeCount++;
            else if (applied === 'highlight_note') highlightCount++;
            else if (applied === 'report_only') reportOnlyCount++;
            written++;
          } catch(e) {
            var fallbackApplied = applyRevisionMark(range, p.iss, 'highlight_note');
            if (fallbackApplied === 'highlight_note') highlightCount++;
            written++;
          }
        }
      });
      return ctx.sync().then(function() {
        showStatus('✅ 已写入 ' + written + ' 条修订标记（高亮+' + highlightCount + ' / 批注+' + nativeCount + ' / 仅报告+' + reportOnlyCount + '）', 'ok');
      });
    });
  }).catch(function(err) {
    showStatus('❌ 修订标记写入失败: ' + err.message, 'err');
  });
}

function exportReport() {
  if (allIssues.length === 0) return;

  var sevLabels = { error: '\u{1F534} 错误', warning: '\u{1F7E1} 存疑', info: '\u{1F535} 建议' };
  var catLabels = {
    spelling: '错别字', grammar: '语病', punctuation: '标点',
    terminology: '术语', consistency: '一致性', expression: '表达'
  };
  var stateLabels = { accepted: '\u2705已修复', ignored: '\u2298已忽略', pending: '\u23F3待处理' };

  var accepted = 0, ignored = 0, pendingCount = 0;
  for (var k in issueStates) {
    if (issueStates[k] === 'accepted') accepted++;
    else if (issueStates[k] === 'ignored') ignored++;
    else pendingCount++;
  }

  Word.run(function(ctx) {
    var body = ctx.document.body;
    // 分隔线
    var sep = body.insertParagraph('————————————————————', 'End');
    sep.font.color = '#c8c6c4';
    // 标题
    var title = body.insertParagraph('智编编辑助手 — 编校报告', 'End');
    title.font.bold = true;
    title.font.size = 12;
    title.font.color = '#0078d4';
    // 统计
    var stats = body.insertParagraph('已修复: ' + accepted + '  |  已忽略: ' + ignored + '  |  待处理: ' + pendingCount, 'End');
    stats.font.size = 10;
    body.insertParagraph('', 'End');
    // 逐条
    allIssues.forEach(function(iss, idx) {
      var state = issueStates[idx] || 'pending';
      var line1 = (idx + 1) + '. ' + (sevLabels[iss.severity] || '') + ' [' + (catLabels[iss.category] || iss.category) + '] — ' + stateLabels[state];
      var p1 = body.insertParagraph(line1, 'End');
      p1.font.bold = true;
      p1.font.size = 10;

      if (iss.original) {
        body.insertParagraph('   原文：' + iss.original, 'End');
      }
      if (iss.suggestion) {
        body.insertParagraph('   建议：' + iss.suggestion, 'End');
      }
      if (iss.reason) {
        var rp = body.insertParagraph('   ' + iss.reason, 'End');
        rp.font.color = '#605e5c';
        rp.font.size = 10;
      }
    });

    return ctx.sync().then(function() {
      showStatus('\u2705 报告已插入文档末尾', 'ok');
    });
  }).catch(function(err) {
    showStatus('\u274C 导出失败: ' + err.message, 'err');
  });
}

function esc(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ========== 参考文献核查 ==========

function startRefCheck() {
  var verifyDoi = document.getElementById('chkVerifyDoi').checked;
  document.getElementById('refProgressText').textContent = '正在读取文档...';
  document.getElementById('refResultCard').style.display = 'none';

  Word.run(function(ctx) {
    var paragraphs = ctx.document.body.paragraphs;
    paragraphs.load('text');
    return ctx.sync().then(function() {
      // 先拼成完整文本，再在每个 [数字] 前插换行，最后按行切分
      var rawLines = [];
      for (var i = 0; i < paragraphs.items.length; i++) {
        rawLines.push(paragraphs.items[i].text);
      }
      var fullText = rawLines.join('\n');
      // 在每个 [数字] 前插换行（只匹配纯数字序号，不影响 [J][M] 等）
      fullText = fullText.replace(/(?=\[\d+\])/g, '\n');
      var lines = fullText.split('\n');

      // 找参考文献起始行
      var refsText = '';
      var refStartIdx = -1;
      for (var j = 0; j < lines.length; j++) {
        var trimmed = lines[j].trim();
        if (/^参考文献\s*$/.test(trimmed) || /^References\s*$/i.test(trimmed)) {
          refStartIdx = j;
          break;
        }
      }
      if (refStartIdx < 0) {
        for (var k = 0; k < lines.length; k++) {
          if (/^\s*\[1\]/.test(lines[k])) {
            refStartIdx = k;
            break;
          }
        }
      }
      if (refStartIdx >= 0) {
        refsText = lines.slice(refStartIdx).join('\n');
      }

      if (!refsText || refsText.trim().length < 5) {
        // 显示文档最后20行，帮助调试
        var lastLines = lines.filter(function(l){ return l.trim(); }).slice(-20);
        document.getElementById('refProgressText').textContent =
          '未找到参考文献。末尾20行：\n' + lastLines.join('\n');
        return;
      }

      var refCount = refsText.split('\n').filter(function(l){ return /^\s*\[\d+\]/.test(l); }).length;
      document.getElementById('refProgressText').textContent =
        '识别到 ' + refCount + ' 条文献，正在核查' + (verifyDoi ? '（含DOI验证，较慢）' : '') + '...';

      return fetch(getApiBase() + '/api/check-refs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          refs_text: refsText,
          body_text: '',
          verify_dois: verifyDoi,
        })
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        document.getElementById('refProgressText').textContent = '';
        renderRefResults(data);
      })
      .catch(function(err) {
        document.getElementById('refProgressText').textContent = '核查失败: ' + err.message;
      });
    });
  }).catch(function(err) {
    document.getElementById('refProgressText').textContent = '读取文档失败: ' + err.message;
  });
}

function renderRefResults(data) {
  var card = document.getElementById('refResultCard');
  var summary = document.getElementById('refSummaryBar');
  var list = document.getElementById('refIssueList');

  card.style.display = 'block';
  summary.textContent = data.summary;

  if (!data.issues || data.issues.length === 0) {
    list.innerHTML = '<div style="color:var(--success); padding:8px">✅ 未发现问题</div>';
    return;
  }

  var sevIcon = { error: '🔴', warning: '🟡', info: '🔵' };
  var catLabel = { format: '格式', doi: 'DOI', metadata: '元数据', citation: '引用' };
  var html = '';
  data.issues.forEach(function(iss) {
    html += '<div class="issue-item" style="margin-bottom:8px; padding:8px; border-left:3px solid ' +
      (iss.severity === 'error' ? '#d13438' : iss.severity === 'warning' ? '#f7630c' : '#0078d4') + '">';
    html += '<div style="font-size:11px; font-weight:600">' +
      (sevIcon[iss.severity] || '') + ' [' + iss.ref_index + '] ' +
      (catLabel[iss.category] || iss.category) + '</div>';
    html += '<div style="font-size:11px; margin-top:3px">' + iss.message + '</div>';
    if (iss.suggestion) {
      html += '<div style="font-size:10px; color:var(--muted); margin-top:2px">💡 ' + iss.suggestion + '</div>';
    }
    if (iss.raw) {
      html += '<div style="font-size:10px; color:var(--muted); margin-top:2px; font-style:italic">' +
        iss.raw.substring(0, 80) + (iss.raw.length > 80 ? '...' : '') + '</div>';
    }
    html += '</div>';
  });
  list.innerHTML = html;
}

// ========== 知识库管理 ==========

function loadKnowledge() {
  fetch(getApiBase() + '/api/knowledge')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var status = document.getElementById('kbStatus');
      var list = document.getElementById('kbSources');
      if (data.total_chunks === 0) {
        status.textContent = '知识库为空，上传规范文档可提升编校准确率';
        list.innerHTML = '';
        return;
      }
      status.textContent = '共 ' + data.total_chunks + ' 个知识片段';
      var html = '';
      data.sources.forEach(function(s) {
        html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0; border-bottom:1px solid var(--border)">';
        html += '<span>📄 ' + s.source + ' (' + s.chunks + '段)</span>';
        html += '<button class="btn btn-sm btn-danger" style="padding:1px 6px; font-size:10px" onclick="deleteKnowledge(\'' + s.source.replace(/'/g, "\\'") + '\')">删除</button>';
        html += '</div>';
      });
      list.innerHTML = html;
    })
    .catch(function() {
      document.getElementById('kbStatus').textContent = '知识库加载失败';
    });
}

function uploadKnowledge() {
  var fileInput = document.getElementById('kbFile');
  if (!fileInput.files || !fileInput.files[0]) {
    showStatus('请先选择文件', 'err');
    return;
  }
  var file = fileInput.files[0];
  var formData = new FormData();
  formData.append('file', file);

  showStatus('正在上传 ' + file.name + '...', 'loading');
  fetch(getApiBase() + '/api/knowledge/upload', { method: 'POST', body: formData })
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || '上传失败'); });
      return r.json();
    })
    .then(function(data) {
      showStatus('✅ 已导入 ' + data.chunks + ' 个知识片段', 'ok');
      fileInput.value = '';
      loadKnowledge();
    })
    .catch(function(err) {
      showStatus('❌ ' + err.message, 'err');
    });
}

function deleteKnowledge(source) {
  if (!confirm('确定删除「' + source + '」？')) return;
  fetch(getApiBase() + '/api/knowledge/' + encodeURIComponent(source), { method: 'DELETE' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      showStatus('已删除 ' + data.deleted + ' 个片段', 'ok');
      loadKnowledge();
    })
    .catch(function() { showStatus('删除失败', 'err'); });
}

// 页面加载时刷新知识库状态
try { loadKnowledge(); } catch(e) {}
