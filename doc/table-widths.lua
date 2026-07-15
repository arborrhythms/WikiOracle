-- Give Markdown pipe tables explicit proportional widths so Pandoc emits
-- wrapping paragraph columns instead of unbounded l/r/c columns in LaTeX.
local widths_by_count = {
  [1] = {0.98},
  [2] = {0.28, 0.70},
  [3] = {0.20, 0.31, 0.47},
  [4] = {0.16, 0.15, 0.18, 0.49},
  [5] = {0.13, 0.10, 0.17, 0.18, 0.40},
  [6] = {0.12, 0.12, 0.09, 0.22, 0.16, 0.27},
}

-- Tables with identifiers or signatures need different proportions from
-- prose-heavy tables that happen to have the same number of columns.
local widths_by_header = {
  ["State unit|Required content|Important metadata|Role"] = {0.14, 0.23, 0.24, 0.37},
  ["Data|Stateful mode|Stateless mode|Upstream exposure"] = {0.16, 0.22, 0.20, 0.40},
  ["Field|Type|Default|Description"] = {0.23, 0.17, 0.14, 0.44},
  ["Field|Type|Shipped value|Description"] = {0.23, 0.17, 0.14, 0.44},
  ["Field|Type|Required|Description"] = {0.23, 0.17, 0.14, 0.44},
  ["Field/attribute|Required|Values or type|Description"] = {0.20, 0.13, 0.20, 0.45},
  ["Name|Type|Shipped model|Endpoint family"] = {0.15, 0.16, 0.25, 0.42},
  ["Variable|Default|Purpose"] = {0.34, 0.24, 0.40},
  ["Function|Purpose"] = {0.36, 0.62},
  ["Operation|Runtime helper|Result"] = {0.17, 0.36, 0.45},
  ["Parameter|Config path|Default|Description"] = {0.19, 0.30, 0.12, 0.37},
  ["Control (DOM id)|Value / default|Storage and behavior"] = {0.25, 0.20, 0.53},
}

local function header_key(tbl)
  if tbl.head == nil or #tbl.head.rows == 0 then
    return ""
  end

  local labels = {}
  for _, cell in ipairs(tbl.head.rows[1].cells) do
    labels[#labels + 1] = pandoc.utils.stringify(cell.contents)
  end
  return table.concat(labels, "|")
end

local function breakable_table_code(code)
  -- Give long paths, XML snippets, and function names legal breaks at their
  -- punctuation. Keep unusual brace-bearing snippets on Pandoc's normal code
  -- path because raw brace escaping would obscure those examples.
  if FORMAT:match("latex") and not code.text:find("[{}]") then
    local escaped = {
      ["\\"] = "\\textbackslash{}",
      ["#"] = "\\#",
      ["$"] = "\\$",
      ["%"] = "\\%",
      ["&"] = "\\&",
      ["_"] = "\\_",
      ["^"] = "\\^{}",
      ["~"] = "\\~{}",
      ["<"] = "\\textless{}",
      [">"] = "\\textgreater{}",
    }
    local break_after = {
      ["_"] = true, ["/"] = true, ["."] = true, [":"] = true,
      ["-"] = true, [">"] = true, [","] = true, [")"] = true,
    }
    local out = {}
    for i = 1, #code.text do
      local char = code.text:sub(i, i)
      out[#out + 1] = escaped[char] or char
      if break_after[char] then
        out[#out + 1] = "\\allowbreak{}"
      end
    end
    return pandoc.RawInline("latex", "\\texttt{" .. table.concat(out) .. "}")
  end
  return code
end

function Table(tbl)
  local n = #tbl.colspecs
  local widths = widths_by_header[header_key(tbl)] or widths_by_count[n]
  if widths == nil then
    widths = {}
    for i = 1, n do
      widths[i] = 0.98 / n
    end
  end

  for i = 1, n do
    tbl.colspecs[i][2] = widths[i]
  end

  return pandoc.walk_block(tbl, {Code = breakable_table_code})
end
