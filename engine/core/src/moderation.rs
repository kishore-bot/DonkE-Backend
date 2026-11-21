//! Chat filter: an Aho-Corasick automaton over normalized characters, so one
//! pass finds every blocked word regardless of list size.
//!
//! Matching ignores case and common digit swaps (`5h1t`), and only masks whole
//! words so names like "Scunthorpe" or "class" are left alone. Indic scripts
//! count as word characters, including vowel signs.
//!
//! A pattern ending in `*` also matches the word with any suffix and masks the
//! whole word. Malayalam, Tamil, Kannada and Telugu attach case endings to the
//! root (മൈര് -> മൈരേ, മൈരൻ), so roots are listed as `മൈര*`.

use std::collections::{HashMap, VecDeque};

fn normalize(character: char) -> char {
    let lower = character.to_lowercase().next().unwrap_or(character);
    match lower {
        '0' => 'o',
        '1' => 'i',
        '3' => 'e',
        '4' | '@' => 'a',
        '5' | '$' => 's',
        '7' => 't',
        other => other,
    }
}

fn is_word(character: char) -> bool {
    character.is_alphanumeric() || matches!(character, '@' | '$' | '\u{0900}'..='\u{0D7F}')
}

#[derive(Clone, Debug, Default)]
struct Node {
    next: HashMap<char, usize>,
    fail: usize,
    /// Blocked words ending here: (length in characters, matches suffixes).
    ends: Vec<(usize, bool)>,
}

#[derive(Clone, Debug)]
pub struct ChatFilter {
    nodes: Vec<Node>,
}

impl ChatFilter {
    pub fn new<S: AsRef<str>>(words: &[S]) -> Self {
        let mut nodes = vec![Node::default()];
        for word in words {
            let trimmed = word.as_ref().trim();
            let (root, prefix) = match trimmed.strip_suffix('*') {
                Some(root) => (root.trim_end(), true),
                None => (trimmed, false),
            };
            let pattern: Vec<char> = root.chars().map(normalize).collect();
            if pattern.is_empty() {
                continue;
            }
            let mut state = 0;
            for character in &pattern {
                state = match nodes[state].next.get(character) {
                    Some(&next) => next,
                    None => {
                        nodes.push(Node::default());
                        let created = nodes.len() - 1;
                        nodes[state].next.insert(*character, created);
                        created
                    }
                };
            }
            let end = (pattern.len(), prefix);
            if !nodes[state].ends.contains(&end) {
                nodes[state].ends.push(end);
            }
        }

        // Breadth-first failure links: the longest proper suffix that is
        // also a prefix of some word.
        let mut queue: VecDeque<usize> = nodes[0].next.values().copied().collect();
        while let Some(state) = queue.pop_front() {
            let edges: Vec<(char, usize)> = nodes[state]
                .next
                .iter()
                .map(|(key, value)| (*key, *value))
                .collect();
            for (character, child) in edges {
                let mut fallback = nodes[state].fail;
                let fail = loop {
                    if let Some(&next) = nodes[fallback].next.get(&character) {
                        break next;
                    }
                    if fallback == 0 {
                        break 0;
                    }
                    fallback = nodes[fallback].fail;
                };
                nodes[child].fail = fail;
                let inherited = nodes[fail].ends.clone();
                nodes[child].ends.extend(inherited);
                queue.push_back(child);
            }
        }
        Self { nodes }
    }

    /// Character ranges `(start, end)` of blocked whole words.
    fn matches(&self, characters: &[char]) -> Vec<(usize, usize)> {
        let normalized: Vec<char> = characters.iter().copied().map(normalize).collect();
        let mut found = Vec::new();
        let mut state = 0;
        for (index, character) in normalized.iter().enumerate() {
            loop {
                if let Some(&next) = self.nodes[state].next.get(character) {
                    state = next;
                    break;
                }
                if state == 0 {
                    break;
                }
                state = self.nodes[state].fail;
            }
            for &(length, prefix) in &self.nodes[state].ends {
                let start = index + 1 - length;
                let mut end = index + 1;
                let clean_start = start == 0 || !is_word(characters[start - 1]);
                let clean_end = end == characters.len() || !is_word(characters[end]);
                if clean_start && (clean_end || prefix) {
                    // A root pattern hides the whole word, suffix included.
                    while prefix && end < characters.len() && is_word(characters[end]) {
                        end += 1;
                    }
                    found.push((start, end));
                }
            }
        }
        found
    }

    pub fn contains(&self, text: &str) -> bool {
        let characters: Vec<char> = text.chars().collect();
        !self.matches(&characters).is_empty()
    }

    /// Replace every character of each blocked word with `*`.
    pub fn censor(&self, text: &str) -> String {
        let mut characters: Vec<char> = text.chars().collect();
        for (start, end) in self.matches(&characters) {
            characters[start..end].fill('*');
        }
        characters.into_iter().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masks_whole_words_case_and_digit_swaps() {
        let filter = ChatFilter::new(&["idiot", "ass", "shit"]);
        assert_eq!(filter.censor("You IDIOT!"), "You *****!");
        assert_eq!(filter.censor("5h1t happens"), "**** happens");
        assert_eq!(filter.censor("first class pass"), "first class pass");
        assert!(!filter.contains("assess the board"));
        assert!(filter.contains("what an ass."));
    }

    #[test]
    fn overlapping_and_nested_words_are_all_found() {
        let filter = ChatFilter::new(&["he", "she", "hers"]);
        assert_eq!(filter.censor("she said hers"), "*** said ****");
    }

    #[test]
    fn malayalam_words_mask_without_splitting_vowel_signs() {
        let filter = ChatFilter::new(&["പട്ടി"]);
        assert_eq!(filter.censor("നീ പട്ടി ആണ്"), "നീ ***** ആണ്");
        // A longer word that only contains the blocked one is left alone.
        assert_eq!(filter.censor("പട്ടികൾ"), "പട്ടികൾ");
    }

    #[test]
    fn root_patterns_match_inflected_words_and_mask_the_whole_word() {
        let filter = ChatFilter::new(&["മൈര*", "lanja*", "kunna"]);
        assert_eq!(filter.censor("പോടാ മൈരേ"), "പോടാ ****");
        assert_eq!(filter.censor("മൈരൻ ആണ്"), "**** ആണ്");
        assert_eq!(filter.censor("lanjakoduku!"), "***********!");
        // Without `*` an inflected form is left alone; a root never matches
        // in the middle of a word.
        assert_eq!(filter.censor("kunnathu"), "kunnathu");
        assert_eq!(filter.censor("അമൈര"), "അമൈര");
    }

    #[test]
    fn empty_lists_and_blank_words_change_nothing() {
        let filter = ChatFilter::new(&["", "   "]);
        assert_eq!(filter.censor("anything goes"), "anything goes");
    }
}
