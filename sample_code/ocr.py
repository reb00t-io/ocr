import asyncio
import logging
import sys

from reb00t.common.llm.llm import LLM
from reb00t.common.llm.response import Response
from reb00t.ocr.backend.image import encode_jpeg_image
from reb00t.ocr.backend.image_cache import ImageCache

debug="--debug" in sys.argv
llm = LLM(cache=debug)
image_cache = ImageCache()

def smoke_test():
    llm = LLM(model="4o", cache=False, instance="smoke_test")
    logging.info(f"Model: {llm.client_provider}/{llm.model['name']}")
    response, _ = asyncio.run(llm.query_simple("Hello, how are you?"))
    logging.info(response)

def parse_response(response_text):
    xml = Response(response_text)
    name = xml.get("name")
    columns = xml.get("columns")
    values = xml.get("values")

    if not values:
        raise ValueError("No values found in response: " + response_text)
    
    if not name:
        raise ValueError("No name found in response: " + response_text)
    
    if not columns:
        raise ValueError("No columns found in response: " + response_text)
    
    columns = columns.split(",")
    if len(columns) != 2:
        raise ValueError("Invalid number of columns found in response: " + columns)

    values = values.strip()
    items = values.split("\n")
    if len(items) > 0 and items[0].startswith("```"):
        items = items[1:]
    if len(items) > 0 and items[-1].startswith("```"):
        items = items[:-1]

    items = [item.strip().split("\t") for item in items]
    items = [item for item in items if len(item) == 2]

    if len(items) == 0:
        raise ValueError("No valid items found in response: " + response_text)
    return name, columns, items

async def generate_name_and_columns(response, primaryLanguage):
    logging.debug("Generating name and columns for vocabulary list", response)
    query = f"""Given the vocabulary list below, create a concise name that young school kids understand.
Don't use the words 'list' or 'vocabulary' in the name, just a descriptive name
assuming it is clear that this is a vocabulary list. Example names are "In the Zoo" or "My Favorite Animals". 
IMPORTANT: The name must not be in the target language, i.e., NOT in {primaryLanguage}, but in the other language of the vocabulary list.
Also return the language codes of the columns as xml, separated by comma.

First, summarize your thoughts on the vocabulary list in a few sentences, then return the name and the language codes of the columns.

Example Response:
<thoughts>The vocabulary languages are English and {primaryLanguage}, language codes en and de. The name must be in English and not {primaryLanguage}.
Good names that are understandable for language learners could be aaa, bbb, ccc, so I choose...
</thoughts>
<name>At home</name>
<columns>en,de</columns>.    <!-- language codes -->

Vocabulary list:
{response}
"""
    name_and_columns, _ = await llm.query_simple(query)
    return name_and_columns

def remove_superfluous_braces(text):
    if (text.startswith("(") and text.endswith(")")):
        return text.replace("(", "").replace(")", "")
    else:
        return text

def fix_braced_translations(response):
    if response is None:
        return None
    
    # fix translations where ALL words are in braces
    response = response.split("\n")
    for i, item in enumerate(response):
        item = item.split("\t")
        if (item[0].startswith("(") and item[0].endswith(")")) or (len(item) > 1 and item[1].startswith("(") and item[1].endswith(")")):
            response[i] = f"{remove_superfluous_braces(item[0])}\t{remove_superfluous_braces(item[1])}"

    return "\n".join(response)

async def detect_optional_words(response, languages):
    logging.debug("Detecting optional words", response)

    # TODO: the correction of terms does not work well, e.g., it doesn't correct 'be fed up (with sth/sb)\tvoll haben'
    query = f"""Given the vocabulary list below (languages {languages}), write for each item, what the minimal answer is to be considered a correct translation that keeps the essential meaning intact, when a kid translates between the languages.

You must process the data in 3 steps and return all 3 steps in the response:

1. First repeat all rows but filter out rows that contain only one word per language. Also:
- Expand abbreviations and write out the full words, e.g., replace "sb", "sth", "smth", "so", "etw" by somebody, something, someone, etwas, ...
- Remove superfluous words, e.g., "hier: " indicating the translation is meant for the given context.
- fix any translation issues that you see

2. In the second step, for each of the filtered rows, think of both translation directions and respond for both. For example, when translating "gehen" into English ("to go"), then the minimal answer is "go" and the word "to" is optional. Sometimes, all words must appear in the translation, for example in a phrase like "What's your name?", the translation should be "Wie heißt Du?", or "Filzstift" is "felt pen".
src → target
- src: minimal_target
- target: minimal_source

Examples:
to go - gehen
- to go: gehen
- gehen: go
dog - der Hund
- dog: Hund
- der Hund: dog
felt pen - Filzstift
- felt pen: Filzstift
- Filzstift: felt pen

3. In the third step, use the generated list from step 2 and the original input to create a condensed output for all rows (also the ones filtered out) and mark optional words using (...). If a translation has multiple alternative answers, list them separated by comma, but DO NOT use braces as the comma denotes a logical OR here. Also fix any translation issues that you see.
Example:
<values>
(to) go\tgehen
dog\t(der) Hund
felt pen\tFilzstift
walk, go\tgehen
(to) put\tlegen, stellen
</values>

Here is the list:
{response}
"""
    response, _ = await llm.query_simple(query)
    if response is None:
        logging.warning("Could not extract optional words: no response from LLM")
        return None
    
    response = Response(response).get("values")
    if response is None:
        logging.warning("Could not extract optional words: no values found")
        return None
    
    response = fix_braced_translations(response)
    if response is None:
        logging.warning("Could not extract optional words: fix_braced_translations failed")
        return None
    
    return response

async def extract_vocabulary_from_file(file_path: str, hash: str, version: int):
    response = image_cache.get(hash)

    if response is None:
        base64_image = encode_jpeg_image(file_path)

        # query_old = """Extract the vocabulary from the image and return the result in TSV format with two columns separated by tab, one column for each language, without header.
        # Only return the vocabulary in code quotes (```), nothing else. Expand abbreviations and write out the full words, e.g., replace "smth", "so", "etw" by something, someone, etwas.
        # If there is no vocabulary in the image, return ```EMPTY```."""

        query = """Extract the vocabulary from the image and return the result in TSV format with two columns separated by tab, one column for each language, without header.
        Only return the vocabulary in code quotes (```), nothing else.
        If there is no vocabulary in the image, return ```EMPTY```."""

        messages = llm.get_messages(query, base64_image=base64_image)
        response, _ = await llm.query(messages)
        stripped_response = response.replace('`', '').strip()

        if "```" in response:
            if len(stripped_response) == 0 or stripped_response == "EMPTY":
                response = "EMPTY"
            else:
                # generate a name for the vocabulary list
                primaryLanguage = "German"
                name_and_columns = await generate_name_and_columns(response, primaryLanguage)
                lang = Response(name_and_columns).get("columns")
                response = await detect_optional_words(response, lang)

                if response is None:
                    response = "EMPTY"

                response = f"""<values>{response}</values>\n{name_and_columns}"""

        image_cache.add(hash, response)

    if response == "EMPTY":
        logging.warning("Empty response, probably no data in image")
        # returning None will result in a 500 response but not cause an error report
        return None

    name, columns, values = parse_response(response)

    # Here you would implement your vocabulary extraction logic.
    # For the sake of example, we return a mock response.
    vocabulary_data = {
        "name": name,
        "columns": columns,
        "vocabulary": values
    }

    # Return success response with extracted vocabulary
    return vocabulary_data