#!/usr/bin/env python3

"""
Test if there is a significant difference between two PDFs using ImageMagick
and pdftocairo.
"""

INFINITY = float('inf')

import os.path, pathlib, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from .constants import DEFAULT_THRESHOLD, DEFAULT_VERBOSITY, DEFAULT_DPI
from .constants import VERB_PRINT_REASON, VERB_PRINT_TMPDIR
from .constants import VERB_PERPAGE, VERB_PRINT_CMD, VERB_ROUGH_PROGRESS
from .constants import DEFAULT_NUM_THREADS

def pdftopng(sourcepath, destdir, basename, verbosity, dpi):
    """
    Invoke pdftocairo to convert the given PDF path to a PNG per page.
    Return a list of page numbers (as strings).
    """
    if [] != list(destdir.glob(basename + '*')):
        raise ValueError("destdir not clean: " + repr(destdir))

    verbose_run((verbosity > VERB_PRINT_CMD),
        [
            'pdftocairo', '-png', '-r', str(dpi), str(sourcepath),
            str(destdir / basename)
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    # list of strings with decimals
    numbers = sorted(path.name for path in destdir.glob(basename + '*' + '.png'))

    return [s[len(basename)+1:-4] for s in numbers]

# returns a float, which can be inf
def imgdiff(a, b, diff, log, print_cmds):
    assert a.is_file()
    assert b.is_file()
    assert not diff.exists()
    assert not log.exists()

    with log.open('wb') as f:
        cmdresult = verbose_run(print_cmds,
            [
                'compare', '-verbose', '-metric', 'PSNR',
                str(a), str(b), str(diff),
            ],
            stdout=f,
            stderr=subprocess.STDOUT,
        )

    if cmdresult.returncode > 1:
        raise ValueError("compare crashed, status="+str(cmdresult.returncode))

    with log.open('r') as f:
        lines = f.readlines()

    if any('image widths or heights differ' in l for l in lines):
        raise ValueError("image widths or heights differ")

    PREF='    all: '
    all_line = [l for l in lines if l.startswith(PREF)]
    assert len(all_line) == 1
    all_str = all_line[0][len(PREF):].strip()
    all_num = INFINITY if all_str == '0' else float(all_str)
    return all_num

def pdfdiff(a, b,
        threshold=DEFAULT_THRESHOLD,
        verbosity=DEFAULT_VERBOSITY,
        dpi=DEFAULT_DPI,
        time_to_inspect=0,
        num_threads=DEFAULT_NUM_THREADS):
    """
    Return True if the PDFs are sufficiently similar.

    The name of this function is slightly confusing: it returns whether the
    PDFs are *not* different.
    """

    assert os.path.isfile(a), "file {} must exist".format(a)
    assert os.path.isfile(b), "file {} must exist".format(b)

    with tempfile.TemporaryDirectory(prefix="diffpdf") as d:
        p = pathlib.Path(d)
        if verbosity >= VERB_PRINT_TMPDIR:
            print("  Temporary directory: {}".format(p))
        if verbosity >= VERB_ROUGH_PROGRESS:
            print("  Converting each page of the PDFs to an image...")

        # expand pdfs to pngs
        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            a_i_ = pool.submit(pdftopng, a, p, "a", verbosity=verbosity, dpi=dpi)
            b_i_ = pool.submit(pdftopng, b, p, "b", verbosity=verbosity, dpi=dpi)

            # Wait for results
            a_i = a_i_.result()
            b_i = b_i_.result()

        if a_i != b_i:
            assert len(a_i) != len(b_i), "mishap with weird page numbers: {} vs {}".format(a_i, b_i)
            if verbosity >= VERB_PRINT_REASON:
                print("Different number of pages: {} vs {}".format(len(a_i), len(b_i)))
            return False
        assert len(a_i) > 0

        if verbosity >= VERB_ROUGH_PROGRESS:
            print("  PDFs have same number of pages. Checking each pair of converted images...")

        significances = []

        for pageno in a_i:
            # remember pageno is a string
            pageapath = p / "a-{}.png".format(pageno)
            pagebpath = p / "b-{}.png".format(pageno)
            diffpath = p / "diff-{}.png".format(pageno)
            logpath = p / "log-{}.txt".format(pageno)
            s = imgdiff(pageapath, pagebpath, diffpath, logpath, (verbosity > VERB_PRINT_CMD))
            if verbosity >= VERB_PERPAGE:
                print("- Page {}: significance={}".format(pageno, s))

            significances.append(s)

        min_significance = min(significances, default=INFINITY)
        significant = (min_significance <= threshold)
        if verbosity >= VERB_PRINT_REASON:
            freetext = "different" if significant else "the same"
            print("Min sig = {}, significant?={}. The PDFs are {}.".format(
                    min_significance, significant, freetext
                ))

        if time_to_inspect > 0:
            print(
                "Waiting for {} seconds before removing temporary directory..."
                .format(time_to_inspect),
                end='',
                flush=True
            )
            time.sleep(time_to_inspect)
            print(" done.")

        return not significant

def verbose_run(print_cmd, args, *restargs, **kw):
    if print_cmd:
        print("  Running: {}".format(' '.join(args)), file=sys.stderr)
    return subprocess.run(args, *restargs, **kw)
