import streamlit as st
from snowflake.snowpark.context import get_active_session
from snowflake.cortex import Complete
from snowflake.core import Root
import pandas as pd
import json


pd.set_option("max_colwidth", None)


import streamlit as st
from snowflake.snowpark import Session
import json

# Snowflake connection parameters (fill with your actual credentials)
connection_parameters = {
   "user": "hdharpure",             # Snowflake username
    "password": "Harshal@9922",     # Snowflake password
    "account": "qu81872.ap-south-1.aws",       # Snowflake account
    "warehouse": "COMPUTE_WH",   # Snowflake warehouse
    "database": "MEDATLAS_AI_CORTEX_SEARCH_DOCS",     # Snowflake database
    "schema": "DATA"          # Snowflake schema   # Snowflake schema
}

# Function to create a Snowpark session
def create_snowpark_session():
    try:
        session = Session.builder.configs(connection_parameters).create()
        return session
    except Exception as e:
        st.error(f"Error creating Snowpark session: {e}")
        return None

# Create the Snowpark session
session = create_snowpark_session()

if session is None:
    st.error("Failed to establish a connection to Snowflake.")
else:
    # Example of accessing a database schema or performing operations
    try:
    # Ensure the service reference is correct
    root = Root(session)
    svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]

    # Replace `query` with `search` (adjust parameters as per API)
    response = svc.search(
        query="SELECT * FROM example_table LIMIT 10",
        columns=COLUMNS,
        limit=NUM_CHUNKS
    )

    # Convert response to DataFrame (if applicable)
    st.write(response.to_pandas())  # Adjust if response format is not directly convertible

 except Exception as e:
    st.error(f"Error in accessing or querying Snowflake: {e}")


### Default Values
NUM_CHUNKS = 3  # Num-chunks provided as context. Play with this to check how it affects your accuracy
slide_window = 7  # how many last conversations to remember. This is the slide window.

# service parameters
CORTEX_SEARCH_DATABASE = "MEDATLAS_AI_CORTEX_SEARCH_DOCS"
CORTEX_SEARCH_SCHEMA = "DATA"
CORTEX_SEARCH_SERVICE = "MEDATLAS_AI_SEARCH_SERVICE_CS"
######



# columns to query in the service
COLUMNS = [
    "chunk",
    "relative_path",
    "category"
]

session = get_active_session()
root = Root(session)

svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]

### Functions

def config_options():
    st.sidebar.selectbox('Select your model:', (
        'mixtral-8x7b',
        'snowflake-arctic',
        'mistral-large',
        'llama3-8b',
        'llama3-70b',
        'reka-flash',
        'mistral-7b',
        'llama2-70b-chat',
        'gemma-7b'), key="model_name")

    categories = session.table('docs_chunks_table').select('category').distinct().collect()

    cat_list = ['ALL']
    for cat in categories:
        cat_list.append(cat.CATEGORY)

    st.sidebar.selectbox('Select what products you are looking for', cat_list, key="category_value")

    st.sidebar.checkbox('Do you want that I remember the chat history?', key="use_chat_history", value=True)

    st.sidebar.checkbox('Debug: Click to see summary generated of previous conversation', key="debug", value=True)
    st.sidebar.button("Start Over", key="clear_conversation", on_click=init_messages)
    st.sidebar.expander("Session State").write(st.session_state)

def init_messages():
    # Initialize chat history
    if st.session_state.clear_conversation or "messages" not in st.session_state:
        st.session_state.messages = []

def get_similar_chunks_search_service(query):
    if st.session_state.category_value == "ALL":
        response = svc.search(query, COLUMNS, limit=NUM_CHUNKS)
    else:
        filter_obj = {"@eq": {"category": st.session_state.category_value}}
        response = svc.search(query, COLUMNS, filter=filter_obj, limit=NUM_CHUNKS)

    st.sidebar.json(response.json())

    return response.json()

def get_chat_history():
    # Get the history from the st.session_stage.messages according to the slide window parameter
    chat_history = []

    start_index = max(0, len(st.session_state.messages) - slide_window)
    for i in range(start_index, len(st.session_state.messages) - 1):
        chat_history.append(st.session_state.messages[i])

    return chat_history

def summarize_question_with_history(chat_history, question):
    # To get the right context, use the LLM to first summarize the previous conversation
    # This will be used to get embeddings and find similar chunks in the docs for context
    prompt = f"""
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natural language. 
        Answer with only the query. Do not add any explanation.

        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        """

    sumary = Complete(st.session_state.model_name, prompt)

    if st.session_state.debug:
        st.sidebar.text("Summary to be used to find similar chunks in the docs:")
        st.sidebar.caption(sumary)

    sumary = sumary.replace("'", "")

    return sumary

def create_prompt(myquestion):
    if st.session_state.use_chat_history:
        chat_history = get_chat_history()

        if chat_history != []:  # There is chat_history, so not first question
            question_summary = summarize_question_with_history(chat_history, myquestion)
            prompt_context = get_similar_chunks_search_service(question_summary)
        else:
            prompt_context = get_similar_chunks_search_service(myquestion)  # First question when using history
    else:
        prompt_context = get_similar_chunks_search_service(myquestion)
        chat_history = ""

    prompt = f"""
           You are an expert chat assistant that extracts information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags..
           When answering the question contained between <question> and </question> tags
           be concise and do not hallucinate. 
           If you don’t have the information just say so.

           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your answer.

           Only answer the question if you can extract it from the CONTEXT provided.

           <chat_history>
           {chat_history}
           </chat_history>
           <context>          
           {prompt_context}
           </context>
           <question>  
           {myquestion}
           </question>
           Answer: 
           """

    json_data = json.loads(prompt_context)

    relative_paths = set(item['relative_path'] for item in json_data['results'])

    return prompt, relative_paths


def answer_question(myquestion):
    prompt, relative_paths = create_prompt(myquestion)

    response = Complete(st.session_state.model_name, prompt)

    return response, relative_paths

def display_image_from_url(url):
    """Display image in the sidebar from URL"""
    if url:
        st.sidebar.image(url, caption="Related Document Image", use_column_width=True)

def main():
    st.title(f":speech_balloon: Chat Document Assistant with Snowflake Cortex 🤖")
    st.write("This is the list of documents you already have and that will be used to answer your questions:")

    docs_available = session.sql("ls @docs").collect()
    list_docs = []
    for doc in docs_available:
        list_docs.append(doc["name"])

    st.dataframe(list_docs)

    config_options()
    init_messages()

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Accept user input
    if question := st.chat_input("What do you want to know about your products? 💬"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(f":pencil: {question}")
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()

            question = question.replace("'", "")

            with st.spinner(f"{st.session_state.model_name} thinking..."):
                response, relative_paths = answer_question(question)
                response = response.replace("'", "")
                message_placeholder.markdown(f":robot: {response}")

                if relative_paths != "None":
                    with st.sidebar.expander("Related Documents 📄"):
                        for path in relative_paths:
                            cmd2 = f"select GET_PRESIGNED_URL(@docs, '{path}', 360) as URL_LINK from directory(@docs)"
                            df_url_link = session.sql(cmd2).to_pandas()
                            url_link = df_url_link._get_value(0, 'URL_LINK')

                            display_url = f"Doc: [{path}]({url_link})"
                            st.sidebar.markdown(display_url)

                            # Displaying image if the relative path is an image
                            if 'image' in path.lower():
                                display_image_from_url(url_link)

        st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
