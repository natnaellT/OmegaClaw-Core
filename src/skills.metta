(= (getSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: (remember string_in_quotes)"
    "- Query long-term embedding memory for skills and memories with short phrases only: (query string_in_quotes)"
    "- Episodes searches history for episodes around a time stamp, time format is same as in TIME: (episodes time_string_in_quotes)"
    "- Pin a certain string as short-term working memory item to keep track of task state: (pin string_in_quotes)"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: (shell string_in_quotes)"
    "- Read file to string: (read-file filename_in_quotes)"
    "- Write string to file: (write-file filename_in_quotes string_in_quotes)"
    "- Append line to file: (append-file filename_in_quotes string_in_quotes)",
    ;COMMUNICATION CHANNELS:
    "- Send message to user: (send string_in_quotes)"
    "- Search the web: (search string_in_quotes)"
    "- Search the web using the Tavily Search Agent: (tavily-search string_in_quotes)"
    "- Get technical analysis for a stock ticker using the Technical Analysis Agent: (technical-analysis ticker_in_quotes)"
   ;BIOLOGICAL ANNOTATION GRAPH:
   "- Index bio output folder (default output): (bio-index) or (bio-index output_dir_in_quotes)"
   "- Force-refresh bio output folder index: (bio-reindex) or (bio-reindex output_dir_in_quotes)"
   "- Query indexed bio atoms with commands stats|folders|predicates|entity ID|node TYPE ID|predicate NAME|folder REL|neighbors ID|neighbors TYPE ID: (bio-query query_in_quotes)"
   "- Query indexed bio atoms in a custom output folder: (bio-query-in output_dir_in_quotes query_in_quotes)"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: (metta sexpression)"
    "Example to invoke Non-Axiomatic Logic via MeTTa: "
    "(metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))"
    "           ((--> garfield animal) (stv 1.0 0.9))))"
    "(metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))"
    "           ((--> (× tiger elephant) eat) (stv 1.0 0.9))))"
    "Also: note the $1 for independent variables, and for negated knowledge use (stv 0.0 0.9)"
    "Additionally |- also works for revision, to merge evidence even when the term of both premises is the same."
    "You can also use PLN:"
    "(metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))"
    "            (Inheritance $1 Bird)) (stv 1.0 0.9))"
    "           ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9))))"))

(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (progn (translatePredicate (open $file write $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (close $Out))
          WRITE-FILE-SUCCESS))

(= (append-file $file $str)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (tavily-search $query)
   (py-call (agentverse.tavily_search $query)))

(= (technical-analysis $ticker)
   (py-call (agentverse.technical_analysis $ticker)))

(= (bio-index)
   (py-call (bio_graph.bio_index)))

(= (bio-index $output_dir)
   (py-call (bio_graph.bio_index $output_dir)))

(= (bio-reindex)
   (py-call (bio_graph.bio_reindex)))

(= (bio-reindex $output_dir)
   (py-call (bio_graph.bio_reindex $output_dir)))

(= (bio-query $query)
   (py-call (bio_graph.bio_query $query)))

(= (bio-query-in $output_dir $query)
   (py-call (bio_graph.bio_query_in $output_dir $query)))

!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)
