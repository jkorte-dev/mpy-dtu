#!/bin/bash
# Intellij IDEA file watcher script: Settings > Tools > File Watchers
# required params:
#
# $FileName$ $FileDir$ $FileDirRelativeToProjectRoot$ $ProjectFileDir$
#
# watches changed python file and compiles to mpy files to dir out
#
# file watcher can also be installed using watchers.xml
#
# run
# mpremote mount out run hoymiles_mpy.py for testing

function compile_all {
  #echo "compile all..." >> watch.log;
  files=$(find hoymiles -name \*.py)
  for f in $files; do
    out="out/${f%.py}.mpy"
    out_dir=$(dirname "${out}")
    test -d "${out_dir}" || mkdir "${out_dir}"
    #echo "mpy-cross -b 6 ${f} -o ${out}"
    mpy-cross -b 6 "${f}" -o "${out}"
  done
}

[[ $# -ne 4 ]] && compile_all && exit

#echo $1 $2 $3 $4 >> $4/watch.log
[[ "$3" == *"testing"* ]] && exit
file=$1
mpy_file=${file%.py}.mpy
#echo "mpy-cross -b 6 $2/$file -o $4/out/$3/$mpy_file" >> $4/watch.log
mkdir -p "$4/out/$3/"
mpy-cross -b 6 "$2/$file" -o "$4/out/$3/$mpy_file"
