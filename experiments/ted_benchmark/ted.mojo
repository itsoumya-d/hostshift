# Zhang-Shasha ordered tree edit distance — Mojo port of the HostShift kernel.
#
# Reference oracle: hostshift/widgettree.py (this port must agree with it to
# 1e-4 on every fixture case; benchmark.py --with-mojo enforces that).
#
# Input format: integer CSV emitted by `benchmark.py --emit fixtures/`:
#   one line per node in postorder: "<kind_code> <leftmost_leaf_postorder_idx>"
#
# Build (pin the toolchain; nightly breakage is expected, not a bug):
#   mojo build ted.mojo -o ted_bench
#   ./ted_bench case_000_a.csv case_000_b.csv     # prints the TED distance
#
# Status: source-complete and fixture-protocol-compatible; the numeric column
# in README.md stays empty until this is compiled with a pinned Mojo >= 1.0
# toolchain. That is deliberate: an unverified timing claim is worse than none.

from sys.argv import argv


alias N_KINDS = 13


fn read_tree(path: String) raises -> (DynamicVector[Int], DynamicVector[Int]):
    # Returns (kind_codes, leftmost_leaf_indices) in postorder.
    var file = open(path, "r")
    var kinds = DynamicVector[Int]()
    var lefts = DynamicVector[Int]()

    @parameter
    fn parse_line(line: String) raises:
        var parts = line.split(" ")
        if parts.size < 2:
            return
        kinds.append(atol(String(parts[0])))
        lefts.append(atol(String(parts[1])))

    for line in file.readlines():
        var stripped = str(line)
        if len(stripped) > 0 and not stripped.is_space():
            parse_line(stripped)
    return (kinds, lefts)


fn atol(s: String) -> Int raises:
    var value = 0
    for byte in s.bytes():
        if byte >= ord("0") and byte <= ord("9"):
            value = value * 10 + Int(byte - ord("0"))
    return value


fn relabel_cost(a_kind: Int, b_kind: Int) -> Float64:
    # Kind mismatch is a full-cost edit; name mismatches are not encoded in the
    # fixture format, so this port measures structural distance only. The
    # Python oracle is driven with default_relabel_cost minus the half-weight
    # name term via kind-only trees in the synthetic ladder; reference-spec
    # cases therefore compare against kind-only expectations too (see README).
    return 0.0 if a_kind == b_kind else 1.0


fn tree_edit_distance(
    a_kinds: DynamicVector[Int],
    a_lefts: DynamicVector[Int],
    b_kinds: DynamicVector[Int],
    b_lefts: DynamicVector[Int],
) -> Float64:
    var m = a_kinds.size
    var n = b_kinds.size

    # Key roots: nodes whose leftmost leaf is seen for the first time from the
    # right — same postorder/keyroot construction as the Python kernel.
    var keyroots_a = keyroots(a_lefts)
    var keyroots_b = keyroots(b_lefts)

    var treedist = DynamicMatrix[Float64](m, n)  # zeros on init

    for i in keyroots_a:
        for j in keyroots_b:
            forest_distance(i, j, a_kinds, a_lefts, b_kinds, b_lefts, treedist)

    return treedist[m - 1, n - 1] if m > 0 and n > 0 else Float64(max(m, n))


fn keyroots(lefts: DynamicVector[Int]) -> DynamicVector[Int]:
    var seen = UnsafeBitSet(lefts.size)
    var out = DynamicVector[Int]()
    var i = Int(lefts.size) - 1
    while i >= 0:
        var lm = lefts[i]
        if not seen[lm]:
            seen[lm] = True
            out.append(i)
        i -= 1
    out.reverse()
    return out


fn forest_distance(
    i: Int,
    j: Int,
    a_kinds: DynamicVector[Int],
    a_lefts: DynamicVector[Int],
    b_kinds: DynamicVector[Int],
    b_lefts: DynamicVector[Int],
    treedist: DynamicMatrix[Float64],
) -> None:
    var li = a_lefts[i]
    var lj = b_lefts[j]
    var rows = i - li + 2
    var cols = j - lj + 1 + 1

    # fd is a local forest-distance table sized to this subproblem.
    var fd = DynamicMatrix[Float64](rows, cols)

    for x in range(1, rows):
        fd[x, 0] = fd[x - 1, 0] + 1.0
    for y in range(1, cols):
        fd[0, y] = fd[0, y - 1] + 1.0

    for x in range(1, rows):
        for y in range(1, cols):
            var ni = li + x - 1
            var nj = lj + y - 1
            if a_lefts[ni] == li and b_lefts[nj] == lj:
                fd[x, y] = min(
                    min(fd[x - 1, y] + 1.0, fd[x, y - 1] + 1.0),
                    fd[x - 1, y - 1] + relabel_cost(a_kinds[ni], b_kinds[nj]),
                )
                treedist[ni, nj] = fd[x, y]
            else:
                var px = a_lefts[ni] - li
                var py = b_lefts[nj] - lj
                fd[x, y] = min(
                    min(fd[x - 1, y] + 1.0, fd[x, y - 1] + 1.0),
                    fd[px, py] + treedist[ni, nj],
                )


fn main() raises:
    if argv.size < 3:
        print("usage: ted_bench <tree_a.csv> <tree_b.csv>")
        return
    var a = read_tree(argv[1])
    var b = read_tree(argv[2])
    print(tree_edit_distance(a[0], a[1], b[0], b[1]))
