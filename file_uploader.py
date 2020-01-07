from __future__ import print_function
import pickle
import os
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from pydrive.drive import GoogleDrive
from pydrive.auth import GoogleAuth

from googleapiclient.http import MediaFileUpload
from googleapiclient.discovery import build
from apiclient import errors
from email.mime.text import MIMEText


def create_message(sender, to, subject, message_text):
    """Create a message for an email.
    Args:
      sender: Email address of the sender.
      to: Email address of the receiver.
      subject: The subject of the email message.
      message_text: The text of the email message.
    Returns:
      An object containing a base64url encoded email object.
    """
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    message = base64.urlsafe_b64encode(message.as_bytes())
    return {'raw': message.decode('utf-8')}


def send_message(mail_service, user_id, message):
    """Send an email message.
    Args:
      mail_service: Authorized Gmail API mail_service instance.
      user_id: User's email address. The special value "me" can be used to indicate the authenticated user.
      message: Message to be sent.
    Returns:
      Sent Message.
    """
    try:
        message = (mail_service.users().messages().send(userId=user_id, body=message).execute())
        print('Message Id: %s' % message['id'])
        return message
    except errors.HttpError as error:
        print('An error occurred: %s' % {error})


def ids_of_messages_matching_query(mail_service, user_id, query_list):
    """List all Messages of the user's mailbox matching the query.
    Args:
    mail_service: Authorized Gmail API mail_service instance.
    user_id: User's email address. The special value "me" can be used to indicate the authenticated user.
    query_list: String list used to filter messages returned.
    Eg.- ['from:user@some_domain.com'] for Messages from a particular sender.
    Returns:
    List of Messages that match the criteria of the query. Note that the returned list contains Message IDs,
    you must use get with the appropriate ID to get the details of a Message.
    """
    emails_id = []
    matches = []
    try:
        for query in query_list:
            response = mail_service.users().messages().list(userId=user_id, q=query).execute()
            if 'messages' in response:
                matches.extend(response['messages'])
            while 'nextPageToken' in response:
                page_token = response['nextPageToken']
                response = mail_service.users().messages().list(userId=user_id, q=query, pageToken=page_token).execute()
                matches.extend(response['messages'])
    except errors.HttpError as error:
        print('An error occurred: %s' % {error})

    # Tricks remove duplicates, to unpack and strip all unnecessary data:
    matching_emails = [dict(tuples) for tuples in {tuple(dictionaries.items()) for dictionaries in matches}]
    for i in matching_emails:
        emails_id.append(i['id'])
    return emails_id


def get_attachments_id(mail_service, user_id, emails_ids):
    """Get and store attachment from Message with given id.
    Args:
      mail_service: Authorized Gmail API mail_service instance.
      user_id: User's email address. The special value "me" can be used to indicate the authenticated user.
      emails_ids: IDs of Messages containing attachments.
      Return:
        Attachments IDs.
    """
    attachments_file_names = []
    emails_id = []
    attachment_ids = []
    mail_data = []
    try:
        # Iterate over emails_ids and fetch their data:
        for ids in emails_ids:
            data = mail_service.users().messages().get(userId=user_id, id=ids, format='full').execute()
            mail_data.append(data)
    except errors.HttpError as error:
        print('An error occurred: %s' % {error})
        # If attachment doesnt exist then don't try get it.
    for email in mail_data:
        if 'parts' in email['payload']:
            # Ranges start at 1, because 0 include body.
            for i in range(1, (len(email['payload']['parts']))):
                parts = email['payload']['parts'][i]
                attachments_file_names.append((parts['filename']))
                attachment_ids.append(parts['body']['attachmentId'])
                emails_id.append(email['id'])
    # Return of three lists to iterate over when saving:
    return {'Emails IDs': emails_id, 'Attachments IDs': attachment_ids,
            'Attachments file names': attachments_file_names}


def save_attachments(mail_service, user_id, attachment_data, save=None):
    # TODO work in progress
    """Get and store attachment from Message with given id.

    Args:
      mail_service: Authorized Gmail API mail_service instance.
      user_id: User's email address. The special value "me" can be used to indicate the authenticated user.
      attachment_data: IDs of emails with attachments, attachments ID's and attachment file names.
      save: Save files on hard drive? Default yes.
      Return:
        Attachment file.
    """
    try:
        # Has to be in range function to be able to iterate over.
        for i in range(0, len(attachment_data['Attachments IDs'])):
            file = mail_service.users().messages().attachments().get(userId=user_id,
                                                                     messageId=attachment_data['Emails IDs'][i],
                                                                     id=attachment_data['Attachments IDs'][i]).execute()
            file_data = base64.urlsafe_b64decode(file['data'].encode('UTF-8'))
            path = attachment_data['Attachments file names'][i]
            if not save:
                with open(path, 'bw') as f:
                    f.write(file_data)
        return file_data

    except errors.HttpError as error:
        print('An error occurred: %s' % {error})

    # path = part['filename']
    #
    # with open(path, 'w') as f:
    #     f.write(file_data)
    # # Save to file:
    # path = ''.join(['C:\somefilefun'], part['filename']])
    # f = open(path, 'w')
    # f.write(file_data)
    # f.close()

    # TODO code prone to errors - make proper error handler:
    # except errors:
    #     print('Unknown error, probably no attachment in emails')


def search_for_file_id(drive_service, type_of_file, name_of_file):
    """Output id of file with exact name and matching type.

    Args:
    drive_service: Authorized Gmail API drive_service instance.
    type_of_file: Query used to filter types of files returned:
                  https://developers.google.com/drive/api/v3/search-files
    name_of_file: String used to filter messages returned.
    Eg.- 'from:user@some_domain.com' for Messages from a particular sender.

    Returns:
    Id of file
    """
    try:
        page_token = None
        while True:
            searched_file = drive_service.files().list(q=type_of_file, pageSize=100, spaces='drive',
                                                       fields='nextPageToken, files(id,name)',
                                                       pageToken=page_token).execute(),
            if page_token is None:
                break
        if not searched_file:
            searched_file_id = create_new_folder(drive_service, name_of_file, [])
            return searched_file_id
        else:
            for name_value in searched_file[0]['files']:
                if name_value['name'] == name_of_file:
                    searched_file_id = name_value['id']
                    return searched_file_id
    except errors.HttpError as error:
        print('An error occurred: %s' % {error})


def create_new_folder(drive_service, folder_name, parent_folder_id):
    """
        Create folder on Google Drive

    Args:
    drive: Authorized Gmail API drive_service instance.
    folder_name: User's email address. The special value "me" can be used to indicate the authenticated user.
    parent_folder_id(optional): String used to filter messages returned.

    Returns:
    Create folder and return it's ID
    """
    try:
        if not parent_folder_id:
            folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        else:

            folder_metadata = {'name': folder_name,
                               'mimeType': 'application/vnd.google-apps.folder',
                               'parents': [{"kind": "drive#fileLink", "id": parent_folder_id}]}

        folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
        # Return folder information:
        return folder['id']
    except errors.HttpError as error:
        print('An error occurred: %s' % {error})


def main():
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    gauth.Authorize()

    mail_service = build('gmail', 'v1', credentials=gauth.credentials)  # Gmail API
    drive_service = build('drive', 'v3', credentials=gauth.credentials)  # Drive API
    # drive = GoogleDrive(gauth)  # PyDrive

    # Examples:
    # Send email example:

    # email_sender = 'example@gmail.com'
    # email_receivers = 'example@gmail.com'
    # email_subject = 'Test'
    # email_content = 'Hello, this is a test'
    # body = create_message(email_sender, email_receivers, email_subject, email_content)
    # mail_service.users().messages().send(userId='me', body=body).execute()

    # Quick testing place:

    # Check for any emails matching query:
    query = ['trzyfaktury']

    emails_ids = ids_of_messages_matching_query(mail_service, 'me', query)
    c = 0
    # simple debug: attachment data fetch
    # filename = []
    # attachment_data_as_bytes = []
    # attachment_data = []
    # mail_data = []
    # # Iterate over emails_ids and fetch their data:
    # for ids in emails_ids:
    #     data = mail_service.users().messages().get(userId='me', id=ids, format='full').execute()
    #     mail_data.append(data)
    #     # If attachment doesnt exist then don't try get it.
    #     # Ranges start at 1, because 0 don't include anything useful.
    #     for email in mail_data:
    #         if 'parts' in email['payload']:
    #             for i in range(1, (len(email['payload']['parts']))):
    #                 parts = email['payload']['parts'][i]
    #                 filename.append((parts['filename']))
    #                 attachment_data_as_bytes.append(
    #                     base64.urlsafe_b64decode(parts['body']['attachmentId'] + "==="))
    #                 attachment_data.append(parts['body']['attachmentId'] + "===")

    # Search for folder ID:
    folderid = (search_for_file_id(drive_service, "mimeType='application/vnd.google-apps.folder'", 'Folder na faktury'))

    # Data from emails:

    attachment_data = get_attachments_id(mail_service, 'me', emails_ids)

    # if i in range(0, len(attachment_data['Attachments IDs'])):
    #     print(i)

    # print(message_id=attachment_data['Emails IDs'][i])
    # print(id=attachment_data['Attachments IDs'][i])
    # print(path=attachment_data['Attachments file names'][i])

    files = save_attachments(mail_service, 'me', attachment_data, None)
    # Decoding test:
    # ASCII = file_data['data'][0].encode('ASCII')
    # decoded = base64.urlsafe_b64decode(ASCII)
    # c = 0
    # singlefilename = file_data['filename'][0]
    # singledata = file_data['as_bytes'][0]

    # file1 = drive.CreateFile()
    # file1.SetContentFile('pliczekdosciagniecia.txt')
    # file1.Upload()

    # filename = []
    # attachment_data_as_bytes = []
    # attachment_data = []
    # mail_attachment_parts = []
    # mail_data has all data from selected email:
    # for ids in emails_ids:
    #     mail_data = (mail_service.users().messages().get(userId='me', id=ids, format='full').execute())
    #     mail_attachment_parts = mail_data['payload']['parts']
    #     for i in range(1, (len(mail_attachment_parts))):
    #         filename.append((mail_attachment_parts[i]['filename']))
    #         attachment_data_as_bytes.append(
    #             base64.urlsafe_b64decode(mail_attachment_parts[i]['body']['attachmentId'] + "==="))
    #         attachment_data.append(mail_attachment_parts[i]['body']['attachmentId'] + "===")

    # with open(jakiesascii, 'bw') as file:
    #     file.write(jakiesascii)


if __name__ == '__main__':
    main()

    # OLD authorization:
    # creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    # if os.path.exists('token.pickle'):
    #     with open('token.pickle', 'rb') as token:
    #         creds = pickle.load(token)
    # # If there are no (valid) credentials available, let the user log in.
    # if not creds or not creds.valid:
    #     if creds and creds.expired and creds.refresh_token:
    #         creds.refresh(Request())
    #     else:
    #         flow = InstalledAppFlow.from_client_secrets_file(
    #             'client_secrets.json', SCOPES)
    #         creds = flow.run_local_server(port=0)
    #     # Save the credentials for the next run
    #     with open('token.pickle', 'wb') as token:
    #         pickle.dump(creds, token)
