from __future__ import print_function
import os
import base64
from pydrive.drive import GoogleDrive
from pydrive.auth import GoogleAuth

from googleapiclient.discovery import build
from apiclient import errors
from email.mime.text import MIMEText

from datetime import date


# Unused imports:
# import pickle
# from google_auth_oauthlib.flow import InstalledAppFlow
# from google.auth.transport.requests import Request
# from googleapiclient.http import MediaFileUpload

# TODO Make proper error handlers:
class FileUploader:
    # Default user is authenticated user.
    user_id = 'me'
    query_list = []
    google_auth = None
    execute_date = date.today().strftime("%B %d, %Y")
    folder_name = ('Files uploaded ' + date.today().strftime("%B %d, %Y"))
    emails_ids = []

    def __init__(self):
        """ Authenticate user for first time then build services.
            First authentication will require user input in browser """
        self.authentication()
        self.mail_service = build('gmail', 'v1', credentials=self.google_auth.credentials)  # Gmail API
        self.drive_service = build('drive', 'v3', credentials=self.google_auth.credentials)  # Drive API
        self.py_drive = GoogleDrive(self.google_auth)  # PyDrive Drive API

    def authentication(self):
        self.google_auth = GoogleAuth()
        self.google_auth.LocalWebserverAuth()
        self.google_auth.Authorize()
        c=0
    def refresh_services(self):
        self.authentication()
        # TODO Check if need to recreate services
        self.mail_service = build('gmail', 'v1', credentials=self.google_auth.credentials)  # Gmail API
        self.drive_service = build('drive', 'v3', credentials=self.google_auth.credentials)  # Drive API
        self.py_drive = GoogleDrive(self.google_auth)  # PyDrive Drive API

    def upload_files(self, query_list=None, folder_name=('Files uploaded ' + date.today().strftime("%B %d, %Y"))):
        """ Execute file upload.
        Args:
            query_list: String list used to filter emails. If not specified then use empty list to avoid error.
            folder_name: Folder name in which filed should be uploaded.
                    If not specified then use default name:'Files uploaded ' + date.today.
         """
        if query_list is not None:
            self.query_list = query_list
        else:
            self.query_list = []
        # To avoid ended session: If token expired then refresh.
        self.refresh_services()
        # Update execute date and folder name:
        self.execute_date = date.today().strftime("%B %d, %Y")
        print('Today is ' + self.execute_date)
        self.folder_name = folder_name
        print('Attachments are uploaded to: "' + self.folder_name + '"')
        # Update emails_ids matching query_list:
        self.ids_of_messages_matching_query()
        # Search for folder ID with given folder name,
        folder_id = (self.search_for_file_id("mimeType='application/vnd.google-apps.folder'", self.folder_name))
        # Data from emails:
        attachment_data = self.get_attachments_ids(self.emails_ids)
        # Save stuff on drive and hard disk:
        self.save_attachments(attachment_data, folder_id, save=False)

    def ids_of_messages_matching_query(self):
        """ List all Messages of the user's mailbox matching the query.
        Returns:
            List of Messages that match the criteria of the query. Note that the returned list contains Message IDs,
            you must use to get the details of a Message. """
        matches = []
        try:
            for query in self.query_list:
                response = self.mail_service.users().messages().list(userId=self.user_id, q=query).execute()
                if 'messages' in response:
                    matches.extend(response.get('messages', []))
                while 'nextPageToken' in response:
                    page_token = response['nextPageToken']
                    response = self.mail_service.users().messages().list(userId=self.user_id, q=query,
                                                                         pageToken=page_token).execute()
                    matches.extend(response['messages'])
        except errors.HttpError as error:
            print('An error occurred: %s' % {error})

        # Tricks to remove duplicates, to unpack and strip all unnecessary data:
        matching_emails = [dict(tuples) for tuples in {tuple(dictionaries.items()) for dictionaries in matches}]
        self.emails_ids = [i['id'] for i in matching_emails]

    def get_attachments_ids(self, emails_ids):
        """ Get all attachments IDs from provided emails IDs.
        Args:
          emails_ids: IDs of Messages containing attachments.
        Return:
            All attachments IDs contained in provided emails_ids in form of dictionary:
            {'Emails IDs':[], 'Attachments IDs':[], 'Attachments file names':[]}.
        """
        attachments_file_names = []
        emails_id = []
        attachment_ids = []
        try:
            # Iterate over emails_ids and get their data:
            mail_data = [self.mail_service.users().messages().get(userId=self.user_id, id=ids, format='full').execute()
                         for ids in emails_ids]
        except errors.HttpError as error:
            print('An error occurred: %s' % {error})
        # If attachment doesn't exist then don't try to get them.
        print('Emails found: ' + str(len(mail_data)))
        for email in mail_data:
            payload = email.get("payload", {})
            parts = payload.get("parts", [])
            for part in parts[1:]:
                try:
                    filename = part.get('filename')
                    attachment_id = part['body']['attachmentId']
                    email_id = email['id']
                except KeyError:
                    print('KeyError in get_attachments_ids: No attachment in email:')
                    print('ID: ' + email['id'])
                else:
                    attachments_file_names.append(filename)
                    attachment_ids.append(attachment_id)
                    emails_id.append(email_id)
        print('Attachments found: ' + str(len(attachment_ids)))

        # Return of three lists to iterate over when saving:
        return {'Emails IDs': emails_id, 'Attachments IDs': attachment_ids,
                'Attachments file names': attachments_file_names}

    def save_attachments(self, attachment_data, drive_folder_id, save=False):
        # TODO rework of this function
        """ Get and save attachments on user GDrive, with option to save them on hard drive.
        Args:
            attachment_data: IDs of emails with attachments, attachments IDs and attachment file names.
            drive_folder_id: ID of folder in GDrive where attachments will be stored.
            save: Save files on hard disk: True/False.
          Return:
            Encoded attachments files. """
        files = []
        files_amount = 0
        # Has to be in range function to be able to iterate over.
        for i in range(0, len(attachment_data['Attachments IDs'])):
            try:
                file = self.mail_service.users().messages().attachments().get(userId=self.user_id,
                                                                              messageId=attachment_data['Emails IDs'][
                                                                                  i],
                                                                              id=attachment_data['Attachments IDs'][
                                                                                  i]).execute()
            except errors.HttpError as error:
                print('An error occurred: %s' % {error})
            else:
                file_data = base64.urlsafe_b64decode(file['data'].encode('UTF-8'))
                path = attachment_data['Attachments file names'][i]
                files.append(file_data)

                if not os.path.splitext(path)[1] == '.jpg' and path:
                    with open(path, 'bw') as f:
                        f.write(file_data)
                    # TODO upload file directly from drive API: Update - not possible for me ATM
                    drive_file = self.py_drive.CreateFile({'parents': [{'id': drive_folder_id}]})
                    drive_file.SetContentFile(path)
                    drive_file.Upload()
                    files_amount += 1
                    # Until PyDrive fix upload() method, then workaround to release file - so it can be deleted:
                    drive_file.SetContentFile("nul")
                    if not save:
                        os.remove(path)

        print('Files saved: ' + str(files_amount))
        return files

    def search_for_file_id(self, type_of_file, name_of_file):
        """ Output id of file or folder with exact name and matching type.
            If folder doesn't exist then create one and return it's ID.
        Args:
            type_of_file: Query used to filter types of files returned:
                          https://developers.google.com/drive/api/v3/search-files
            name_of_file: String used to filter messages or folders returned.
            Eg.- 'from:user@some_domain.com' for Messages from a particular sender.
        Returns:
            Id of file or folder. """
        try:
            page_token = None

            while True:
                searched_file = self.drive_service.files().list(q=type_of_file, pageSize=100, spaces='drive',
                                                                fields='nextPageToken, files(id,name)',
                                                                pageToken=page_token).execute(),
                if page_token is None:
                    break
            # If folder doesn't exist and user try to get ID, then create that folder and return ID.
            # TODO if folder is trashed function should un-trash it
            if searched_file:
                for name_value in searched_file[0]['files']:
                    if name_value['name'] == name_of_file:
                        searched_file_id = name_value['id']
                        return searched_file_id
            elif type_of_file == "mimeType='application/vnd.google-apps.folder'":
                searched_file_id = self.create_new_folder(name_of_file, [])
                return searched_file_id
        except errors.HttpError as error:
            print('An error occurred: %s' % {error})

    def create_new_folder(self, folder_name, parent_folder_id=None):
        """ Create folder on Google Drive
        Args:
            folder_name: name for created folder
            parent_folder_id(optional): String used to filter messages returned.
        Returns:
            Create folder and return it's ID. """
        if not parent_folder_id:
            folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        else:
            folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder',
                               'parents': [{"kind": "drive#fileLink", "id": parent_folder_id}]}
        try:
            folder = self.drive_service.files().create(body=folder_metadata, fields='id').execute()
            # Return folder information:
            return folder['id']
        except errors.HttpError as error:
            print('An error occurred: %s' % {error})

    # Part of old code, but it might get useful some day:
    @staticmethod
    def create_message(sender, to, subject, message_text):
        """ Create a message for an email.
        Args:
            sender: Email address of the sender.
            to: Email address of the receiver.
            subject: The subject of the email message.
            message_text: The text of the email message.
        Returns:
            An object containing a base64url encoded email object. """
        message = MIMEText(message_text)
        message['to'] = to
        message['from'] = sender
        message['subject'] = subject
        message = base64.urlsafe_b64encode(message.as_bytes())
        return {'raw': message.decode('utf-8')}

    @staticmethod
    def send_message(mail_service, user_id, message):
        """ Send an email message.
        Args:
            mail_service: Authorized Gmail API instance.
            user_id: User's email address. The special value "me" can be used to indicate the authenticated user.
            message: Message to be sent.
        Returns:
            Sent Message. """
        try:
            message = (mail_service.users().messages().send(userId=user_id, body=message).execute())
            print('Message Id: %s' % message['id'])
            return message
        except errors.HttpError as error:
            print('An error occurred: %s' % {error})

    # Send email example:

    # email_sender = 'example@gmail.com'
    # email_receivers = 'example@gmail.com'
    # email_subject = 'Test'
    # email_content = 'Hello, this is a test'
    # body = create_message(email_sender, email_receivers, email_subject, email_content)
    # mail_service.users().messages().send(userId='me', body=body).execute()


def main():
    # User inputs:
    queries = ['label:Faktury']
    folder_name = 'Folder na faktury'
    FileUploader().upload_files(query_list=queries, folder_name=folder_name)


if __name__ == '__main__':
    main()
